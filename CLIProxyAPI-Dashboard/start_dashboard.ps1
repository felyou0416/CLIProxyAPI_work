param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Import-DashboardEnv {
    $envFile = Join-Path $scriptDir '.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return }
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or $line -notmatch '=') { return }
        $parts = $line.Split('=', 2)
        if ($parts.Count -lt 2) { return }
        $k = $parts[0].Trim()
        $v = $parts[1].Trim().Trim('"').Trim("'")
        if (-not $k) { return }
        # Process-level only; never overwrite an already-set env var.
        if (-not [Environment]::GetEnvironmentVariable($k, 'Process')) {
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ListeningPids {
    param([int]$Port)

    $pids = New-Object 'System.Collections.Generic.HashSet[int]'

    # Prefer netstat: faster and works without the NetTCPIP module.
    try {
        $pattern = "^\s*TCP\s+(\S+):$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
        $lines = & netstat -ano -p tcp 2>$null
        foreach ($line in $lines) {
            $m = [regex]::Match([string]$line, $pattern)
            if (-not $m.Success) { continue }
            $local = $m.Groups[1].Value
            if ($local -notin @('127.0.0.1', '0.0.0.0', '[::1]', '[::]', '::1', '::')) { continue }
            [void]$pids.Add([int]$m.Groups[2].Value)
        }
    } catch {
        # fall through
    }

    if ($pids.Count -eq 0) {
        try {
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                ForEach-Object { if ($_.OwningProcess) { [void]$pids.Add([int]$_.OwningProcess) } }
        } catch {
            # ignore
        }
    }

    return @($pids)
}

function Test-DashboardPortProxy {
    param([string]$Port)
    $pattern = "^\s*0\.0\.0\.0\s+$([regex]::Escape($Port))\s+127\.0\.0\.1\s+$([regex]::Escape($Port))\s*$"
    try {
        return [bool]((netsh interface portproxy show v4tov4) | Select-String -Pattern $pattern)
    } catch {
        return $false
    }
}

function Invoke-ElevatedPowerShell {
    param(
        [string]$Script,
        [switch]$Wait
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded)
    if (Test-IsAdministrator) {
        if ($Wait) {
            Start-Process -WindowStyle Hidden -FilePath powershell -ArgumentList $args -Wait | Out-Null
        } else {
            Start-Process -WindowStyle Hidden -FilePath powershell -ArgumentList $args | Out-Null
        }
        return $true
    }
    try {
        if ($Wait) {
            $p = Start-Process -Verb RunAs -FilePath powershell -ArgumentList $args -Wait -PassThru
            return ($p.ExitCode -eq 0 -or $null -eq $p.ExitCode)
        }
        Start-Process -Verb RunAs -FilePath powershell -ArgumentList $args | Out-Null
        return $true
    } catch {
        Write-Warning "UAC elevation was cancelled or failed: $($_.Exception.Message)"
        return $false
    }
}

function Test-LocalHttpReady {
    param(
        [string]$Url,
        [int]$TimeoutMs = 800
    )
    try {
        # Force direct loopback — never go through system/HTTP_PROXY.
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = 'GET'
        $req.Timeout = $TimeoutMs
        $req.ReadWriteTimeout = $TimeoutMs
        $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
        $req.KeepAlive = $false
        try {
            $resp = $req.GetResponse()
            $code = [int]$resp.StatusCode
            $resp.Close()
            return ($code -ge 200 -and $code -lt 500)
        } catch [System.Net.WebException] {
            $resp = $_.Exception.Response
            if ($null -ne $resp) {
                $code = [int]$resp.StatusCode
                $resp.Close()
                # Auth-required (401) still means the server is up.
                return ($code -ge 200 -and $code -lt 500)
            }
            return $false
        }
    } catch {
        return $false
    }
}

Import-DashboardEnv

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "python/py was not found. Install Python or make sure it is available on PATH."
    exit 1
}

$dashboardHost = if ($env:CLIPROXYAPI_DASHBOARD_HOST) { $env:CLIPROXYAPI_DASHBOARD_HOST.Trim() } else { '127.0.0.1' }
$dashboardPort = if ($env:CLIPROXYAPI_DASHBOARD_PORT) { $env:CLIPROXYAPI_DASHBOARD_PORT.Trim() } else { '8765' }
if ([string]::IsNullOrWhiteSpace($dashboardHost)) { $dashboardHost = '127.0.0.1' }
if ([string]::IsNullOrWhiteSpace($dashboardPort)) { $dashboardPort = '8765' }
$openHost = if ($dashboardHost -eq '0.0.0.0') { '127.0.0.1' } else { $dashboardHost }
$dashboardUrl = "http://${openHost}:${dashboardPort}"
$healthUrl = "http://127.0.0.1:${dashboardPort}/"

Write-Host "Starting CLIProxyAPI Dashboard Panel..." -ForegroundColor Cyan
Write-Host "Directory: $scriptDir"
Write-Host "Open: $dashboardUrl" -ForegroundColor Green
Write-Host "Bind: ${dashboardHost}:${dashboardPort}" -ForegroundColor DarkCyan

$logDir = Join-Path $scriptDir '..\CLIProxyAPI\storage\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutLog = Join-Path $logDir 'dashboard.stdout.log'
$stderrLog = Join-Path $logDir 'dashboard.stderr.log'

# If something is already healthy on the port, reuse it (no network needed).
if (Test-LocalHttpReady -Url $healthUrl) {
    Write-Host "Dashboard is already running at $dashboardUrl" -ForegroundColor Green
    if ($OpenBrowser) {
        Start-Process $dashboardUrl | Out-Null
    }
    exit 0
}

$restoreDashboardPortProxy = $false
if ($dashboardHost -eq '127.0.0.1' -and (Test-DashboardPortProxy -Port $dashboardPort)) {
    $restoreDashboardPortProxy = $true
    Write-Host "Temporarily removing dashboard portproxy on 0.0.0.0:$dashboardPort so the local backend can bind first ..." -ForegroundColor Yellow
    $ok = Invoke-ElevatedPowerShell -Wait -Script @"
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort | Out-Null
"@
    if (-not $ok) {
        Write-Warning "Could not adjust portproxy (UAC cancelled?). Continuing with local bind attempt."
        $restoreDashboardPortProxy = $false
    }
}

Write-Host "Stopping any existing listener on port $dashboardPort ..." -ForegroundColor Yellow
$existingPids = Get-ListeningPids -Port ([int]$dashboardPort)
foreach ($existingPid in $existingPids) {
    try {
        Stop-Process -Id $existingPid -Force -ErrorAction Stop
        Write-Host "Stopped old process PID $existingPid" -ForegroundColor DarkYellow
    } catch {
        Write-Warning "Failed to stop PID ${existingPid}: $($_.Exception.Message)"
    }
}
if ($existingPids.Count -gt 0) {
    Start-Sleep -Milliseconds 400
}

if ($restoreDashboardPortProxy) {
    # Fire-and-forget restore. Do not block startup on a second UAC prompt.
    Write-Host "Scheduling dashboard portproxy restore after local backend is ready ..." -ForegroundColor DarkCyan
    Invoke-ElevatedPowerShell -Script @"
`$ErrorActionPreference = 'SilentlyContinue'
`$deadline = (Get-Date).AddSeconds(60)
`$listener = `$false
while ((Get-Date) -lt `$deadline) {
    `$lines = netstat -ano -p tcp 2>`$null
    foreach (`$line in `$lines) {
        if (`$line -match "LISTENING\s+\d+\s*$" -and `$line -match ":$dashboardPort\s+") {
            `$listener = `$true
            break
        }
    }
    if (`$listener) { break }
    Start-Sleep -Seconds 1
}
if (`$listener) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort connectaddress=127.0.0.1 connectport=$dashboardPort | Out-Null
}
"@ | Out-Null
}

# Clear previous log tails so a failed start is obvious.
try {
    Set-Content -LiteralPath $stdoutLog -Value "" -Encoding utf8
    Set-Content -LiteralPath $stderrLog -Value "" -Encoding utf8
} catch {
    # ignore log reset failures
}

$env:PYTHONUNBUFFERED = '1'
$env:CLIPROXYAPI_AUTO_START = if ($env:CLIPROXYAPI_AUTO_START) { $env:CLIPROXYAPI_AUTO_START } else { '1' }

# Ensure Python loopback calls are not hijacked by a dead system proxy.
if (-not $env:NO_PROXY) {
    $env:NO_PROXY = '127.0.0.1,localhost,::1'
} elseif ($env:NO_PROXY -notmatch '127\.0\.0\.1') {
    $env:NO_PROXY = "127.0.0.1,localhost,::1,$($env:NO_PROXY)"
}

try {
    $proc = Start-Process -WindowStyle Hidden -FilePath $python.Source -ArgumentList @('.\app.py') -WorkingDirectory $scriptDir -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
} catch {
    Write-Error "Failed to launch python: $($_.Exception.Message)"
    exit 1
}

Write-Host "Dashboard backend launching. PID: $($proc.Id)" -ForegroundColor Green
Write-Host "Logs: $stdoutLog" -ForegroundColor DarkCyan

$ready = $false
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        break
    }
    if (Test-LocalHttpReady -Url $healthUrl) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 300
}

if ($ready) {
    Write-Host "Dashboard is ready at $dashboardUrl" -ForegroundColor Green
    if ($OpenBrowser) {
        Start-Process $dashboardUrl | Out-Null
    }
    exit 0
}

$stderrTail = ''
$stdoutTail = ''
try { $stderrTail = (Get-Content -LiteralPath $stderrLog -ErrorAction SilentlyContinue | Select-Object -Last 20) -join "`n" } catch {}
try { $stdoutTail = (Get-Content -LiteralPath $stdoutLog -ErrorAction SilentlyContinue | Select-Object -Last 20) -join "`n" } catch {}

Write-Host ""
Write-Host "Dashboard failed to become ready on $dashboardUrl" -ForegroundColor Red
if ($proc.HasExited) {
    Write-Host "Python process exited early with code $($proc.ExitCode)." -ForegroundColor Red
} else {
    Write-Host "Python process is still running (PID $($proc.Id)) but port $dashboardPort is not answering." -ForegroundColor Red
}
if ($stdoutTail) {
    Write-Host "---- stdout (tail) ----" -ForegroundColor Yellow
    Write-Host $stdoutTail
}
if ($stderrTail) {
    Write-Host "---- stderr (tail) ----" -ForegroundColor Yellow
    Write-Host $stderrTail
}
Write-Host "Full logs:" -ForegroundColor Yellow
Write-Host "  $stdoutLog"
Write-Host "  $stderrLog"
exit 1
