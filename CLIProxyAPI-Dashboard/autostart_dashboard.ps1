param(
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$StartNow,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboardScript = Join-Path $scriptDir 'start_dashboard.ps1'
$startupDir = [Environment]::GetFolderPath('Startup')
$launcherPath = Join-Path $startupDir 'CLIProxyAPI Dashboard.cmd'
$legacyShortcutPath = Join-Path $startupDir 'CLIProxyAPI Dashboard.lnk'

function Get-AutostartCmdContent {
    param([switch]$Open)
    $openFlag = if ($Open) { ' -OpenBrowser' } else { '' }
    @"
@echo off
setlocal
set "DASHBOARD_ROOT=$scriptDir"
set "LOG_DIR=%DASHBOARD_ROOT%\..\CLIProxyAPI\storage\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\dashboard.autostart.log"
echo ===== %DATE% %TIME% autostart begin =====>>"%LOG_FILE%"
rem Wait for desktop / user profile / PATH to settle after logon.
timeout /t 12 /nobreak >nul
cd /d "%DASHBOARD_ROOT%" >>"%LOG_FILE%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%DASHBOARD_ROOT%\start_dashboard.ps1"$openFlag >>"%LOG_FILE%" 2>&1
echo exit_code=%ERRORLEVEL%>>"%LOG_FILE%"
echo ===== %DATE% %TIME% autostart end =====>>"%LOG_FILE%"
endlocal
"@
}

function Write-AutostartStatus {
    if (Test-Path -LiteralPath $launcherPath) {
        Write-Host "Startup launcher is installed:" -ForegroundColor Green
        Write-Host $launcherPath
        return
    }
    if (Test-Path -LiteralPath $legacyShortcutPath) {
        Write-Host "Legacy startup shortcut is installed:" -ForegroundColor Yellow
        Write-Host $legacyShortcutPath
        return
    }
    Write-Host "Startup launcher is not installed:" -ForegroundColor Yellow
    Write-Host $launcherPath
}

if (-not (Test-Path -LiteralPath $dashboardScript)) {
    throw "Dashboard startup script not found: $dashboardScript"
}

if ($Uninstall) {
    $removed = $false
    foreach ($path in @($launcherPath, $legacyShortcutPath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "Removed:" -ForegroundColor Green
            Write-Host $path
            $removed = $true
        }
    }
    if (-not $removed) {
        Write-Host "Startup launcher was not installed:" -ForegroundColor Yellow
        Write-Host $launcherPath
    }
    return
}

if ($Status) {
    Write-AutostartStatus
    return
}

New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
Set-Content -LiteralPath $launcherPath -Value (Get-AutostartCmdContent -Open:$OpenBrowser) -Encoding ASCII
if (Test-Path -LiteralPath $legacyShortcutPath) {
    Remove-Item -LiteralPath $legacyShortcutPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Installed startup launcher:" -ForegroundColor Green
Write-Host $launcherPath
Write-Host "Target: $dashboardScript"
Write-Host "Boot log: $(Join-Path $scriptDir '..\CLIProxyAPI\storage\logs\dashboard.autostart.log')"

if ($StartNow) {
    Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', $dashboardScript
    ) -WorkingDirectory $scriptDir
    Write-Host "Started dashboard now." -ForegroundColor Green
}

Write-AutostartStatus
