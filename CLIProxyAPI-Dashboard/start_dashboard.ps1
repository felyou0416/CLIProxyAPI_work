param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "python/py was not found. Install Python or make sure it is available on PATH."
    exit 1
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
        return
    }
    if ($Wait) {
        Start-Process -Verb RunAs -FilePath powershell -ArgumentList $args -Wait | Out-Null
    } else {
        Start-Process -Verb RunAs -FilePath powershell -ArgumentList $args | Out-Null
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$dashboardHost = if ($env:CLIPROXYAPI_DASHBOARD_HOST) { $env:CLIPROXYAPI_DASHBOARD_HOST.Trim() } else { '127.0.0.1' }
$dashboardPort = if ($env:CLIPROXYAPI_DASHBOARD_PORT) { $env:CLIPROXYAPI_DASHBOARD_PORT.Trim() } else { '8765' }
if ([string]::IsNullOrWhiteSpace($dashboardHost)) { $dashboardHost = '127.0.0.1' }
if ([string]::IsNullOrWhiteSpace($dashboardPort)) { $dashboardPort = '8765' }
$openHost = if ($dashboardHost -eq '0.0.0.0') { '127.0.0.1' } else { $dashboardHost }
$dashboardUrl = "http://${openHost}:${dashboardPort}"
Write-Host "Starting CLIProxyAPI Dashboard Panel..." -ForegroundColor Cyan
Write-Host "Directory: $scriptDir"
Write-Host "Open: $dashboardUrl" -ForegroundColor Green
Write-Host "Bind: ${dashboardHost}:${dashboardPort}" -ForegroundColor DarkCyan
$logDir = Join-Path $scriptDir '..\CLIProxyAPI\storage\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutLog = Join-Path $logDir 'dashboard.stdout.log'
$stderrLog = Join-Path $logDir 'dashboard.stderr.log'

$restoreDashboardPortProxy = $false
if ($dashboardHost -eq '127.0.0.1' -and (Test-DashboardPortProxy -Port $dashboardPort)) {
    $restoreDashboardPortProxy = $true
    Write-Host "Temporarily removing dashboard portproxy on 0.0.0.0:$dashboardPort so the local backend can bind first ..." -ForegroundColor Yellow
    Invoke-ElevatedPowerShell -Wait -Script @"
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort | Out-Null
"@
}

Write-Host "Stopping any existing dashboard on port $dashboardPort ..." -ForegroundColor Yellow
$existingPid = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $dashboardPort -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess
if ($null -ne $existingPid) {
    try {
        Stop-Process -Id $existingPid -Force -ErrorAction Stop
        Write-Host "Stopped old dashboard PID $existingPid" -ForegroundColor DarkYellow
        Start-Sleep -Milliseconds 300
    } catch {
        Write-Warning "Failed to stop PID ${existingPid}: $($_.Exception.Message)"
    }
}

if ($restoreDashboardPortProxy) {
    Write-Host "Preparing dashboard portproxy restore after local backend is ready ..." -ForegroundColor DarkCyan
    Invoke-ElevatedPowerShell -Script @"
`$ErrorActionPreference = 'SilentlyContinue'
`$deadline = (Get-Date).AddSeconds(60)
`$listener = `$null
while ((Get-Date) -lt `$deadline) {
    `$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $dashboardPort -State Listen -ErrorAction SilentlyContinue
    if (`$listener) { break }
    Start-Sleep -Seconds 1
}
if (`$listener) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$dashboardPort connectaddress=127.0.0.1 connectport=$dashboardPort | Out-Null
}
"@
}

if ($OpenBrowser) {
    Start-Process $dashboardUrl | Out-Null
}

$env:PYTHONUNBUFFERED = '1'
$env:CLIPROXYAPI_AUTO_START = if ($env:CLIPROXYAPI_AUTO_START) { $env:CLIPROXYAPI_AUTO_START } else { '1' }
$proc = Start-Process -WindowStyle Hidden -FilePath $python.Source -ArgumentList @('.\app.py') -WorkingDirectory $scriptDir -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
Write-Host "Dashboard backend started in background. PID: $($proc.Id)" -ForegroundColor Green
Write-Host "Logs: $stdoutLog" -ForegroundColor DarkCyan
