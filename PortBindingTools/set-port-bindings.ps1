param(
    [Parameter(Mandatory = $true)]
    [object[]]$Ports,

    [string]$ListenAddress = '0.0.0.0',
    [string]$ConnectAddress = '127.0.0.1',
    [string[]]$RemoteAddress = @('fd7a:115c:a1e0::9e39:c580', '100.89.197.128'),

    [switch]$Firewall,
    [switch]$Remove,
    [switch]$Status,
    [switch]$Elevate
)

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Normalize-Ports {
    $result = @()
    foreach ($item in $Ports) {
        foreach ($candidate in ([string]$item -split '[,\s;]+')) {
            if (-not $candidate) { continue }
            $port = 0
            if (-not [int]::TryParse($candidate, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
                throw "Invalid port: $candidate"
            }
            if ($result -notcontains $port) {
                $result += $port
            }
        }
    }
    if ($result.Count -eq 0) {
        throw "At least one port is required."
    }
    return $result
}

function Normalize-RemoteAddresses {
    if (-not $RemoteAddress -or $RemoteAddress.Count -eq 0) {
        throw "At least one -RemoteAddress IP or CIDR is required. Do not use Any."
    }
    $result = @()
    foreach ($item in $RemoteAddress) {
        foreach ($candidate in ([string]$item -split '[,\s;]+')) {
            if (-not $candidate) { continue }
            if ($candidate.Trim().ToLowerInvariant() -eq 'any') {
                throw "RemoteAddress Any is not allowed. Use specific IPs or CIDR ranges."
            }
            if ($result -notcontains $candidate.Trim()) {
                $result += $candidate.Trim()
            }
        }
    }
    if ($result.Count -eq 0) {
        throw "At least one -RemoteAddress IP or CIDR is required."
    }
    return $result
}

function Invoke-SelfElevated {
    $argsList = @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        "`"$PSCommandPath`"",
        '-Ports',
        ($Ports -join ','),
        '-ListenAddress',
        $ListenAddress,
        '-ConnectAddress',
        $ConnectAddress,
        '-RemoteAddress',
        ($RemoteAddress -join ',')
    )
    if ($Firewall) { $argsList += '-Firewall' }
    if ($Remove) { $argsList += '-Remove' }
    if ($Status) { $argsList += '-Status' }
    Start-Process -Verb RunAs -FilePath powershell -ArgumentList $argsList
}

function Get-PortproxyRows {
    $raw = netsh interface portproxy show v4tov4
    $rows = @()
    foreach ($line in $raw) {
        $text = [string]$line
        if ($text -match '^\s*(\d{1,3}(?:\.\d{1,3}){3}|\*)\s+(\d+)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s*$') {
            $rows += [pscustomobject]@{
                ListenAddress = $matches[1]
                ListenPort = [int]$matches[2]
                ConnectAddress = $matches[3]
                ConnectPort = [int]$matches[4]
            }
        }
    }
    return $rows
}

function Show-Status {
    $portSet = @{}
    foreach ($port in $Ports) { $portSet[$port] = $true }

    Write-Host "TCP listeners:" -ForegroundColor Cyan
    $listenerRows = @()
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    foreach ($listener in $listeners) {
        $port = [int]$listener.Port
        if (-not $portSet.ContainsKey($port)) { continue }
        $listenerRows += [pscustomobject]@{
            LocalAddress = [string]$listener.Address
            LocalPort = $port
            State = 'LISTENING'
        }
    }
    $listenerRows | Sort-Object LocalPort, LocalAddress | Format-Table -AutoSize

    Write-Host "Portproxy rules:" -ForegroundColor Cyan
    Get-PortproxyRows |
        Where-Object { $portSet.ContainsKey([int]$_.ListenPort) -or $portSet.ContainsKey([int]$_.ConnectPort) } |
        Sort-Object ListenPort, ListenAddress |
        Format-Table -AutoSize

    Write-Host "Firewall rules:" -ForegroundColor Cyan
    $firewallRows = @()
    foreach ($port in $Ports) {
        $name = "CLIProxyAPI Portproxy TCP $port"
        $detail = netsh advfirewall firewall show rule name="$name" verbose
        if (($detail -join "`n") -match 'No rules match') { continue }
        $fields = @{}
        foreach ($line in $detail) {
            if ([string]$line -match '^\s*([^:]+):\s*(.*?)\s*$') {
                $fields[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
        if ($fields.Count -gt 0) {
            $firewallRows += [pscustomobject]@{
                Name = $name
                Enabled = $fields['Enabled']
                Action = $fields['Action']
                Direction = $fields['Direction']
                Profile = $fields['Profiles']
                Protocol = $fields['Protocol']
                LocalPort = $fields['LocalPort']
                RemoteIP = $fields['RemoteIP']
            }
        }
    }
    $firewallRows | Sort-Object LocalPort | Format-Table -AutoSize
}

function Set-PortproxyRule {
    param([int]$Port)
    netsh interface portproxy delete v4tov4 listenaddress=$ListenAddress listenport=$Port | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=$ListenAddress listenport=$Port connectaddress=$ConnectAddress connectport=$Port | Out-Null
}

function Remove-PortproxyRule {
    param([int]$Port)
    netsh interface portproxy delete v4tov4 listenaddress=$ListenAddress listenport=$Port | Out-Null
}

function Set-FirewallRule {
    param([int]$Port)
    $name = "CLIProxyAPI Portproxy TCP $Port"
    $remoteValue = $RemoteAddress -join ','
    netsh advfirewall firewall delete rule name="$name" | Out-Null
    netsh advfirewall firewall add rule name="$name" dir=in action=allow protocol=TCP localport=$Port remoteip="$remoteValue" profile=any description="Allow LAN access to TCP port $Port through Windows portproxy" | Out-Null
}

function Remove-FirewallRule {
    param([int]$Port)
    $name = "CLIProxyAPI Portproxy TCP $Port"
    netsh advfirewall firewall delete rule name="$name" | Out-Null
}

$Ports = Normalize-Ports
if (-not $Remove -and -not $Status) {
    $RemoteAddress = Normalize-RemoteAddresses
}

if ($Elevate -and -not (Test-Admin)) {
    Invoke-SelfElevated
    Write-Host "Administrator approval requested. Confirm the UAC prompt, then rerun with -Status." -ForegroundColor Yellow
    exit 0
}

if ($Status) {
    Show-Status
    if (-not $Remove) { exit 0 }
}

if (-not (Test-Admin)) {
    throw "Administrator privileges are required. Rerun with -Elevate or start PowerShell as Administrator."
}

foreach ($port in $Ports) {
    if ($Remove) {
        Remove-PortproxyRule -Port $port
        Remove-FirewallRule -Port $port
        Write-Host "Removed portproxy rule for TCP ${ListenAddress}:$port" -ForegroundColor Yellow
        continue
    }

    Set-PortproxyRule -Port $port
    if ($Firewall) {
        Set-FirewallRule -Port $port
    }
    Write-Host "Mapped TCP ${ListenAddress}:$port -> ${ConnectAddress}:$port" -ForegroundColor Green
}

Show-Status
