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
$shortcutPath = Join-Path $startupDir 'CLIProxyAPI Dashboard.lnk'

function New-DashboardShortcut {
    param(
        [string]$Path,
        [string]$TargetScript,
        [string]$WorkingDirectory,
        [switch]$Open
    )

    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', "`"$TargetScript`""
    )
    if ($Open) {
        $arguments += '-OpenBrowser'
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = $arguments -join ' '
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Start CLIProxyAPI Dashboard when Windows logs in.'
    $shortcut.Save()
}

function Write-AutostartStatus {
    if (Test-Path -LiteralPath $shortcutPath) {
        Write-Host "Startup shortcut is installed:" -ForegroundColor Green
        Write-Host $shortcutPath
        return
    }

    Write-Host "Startup shortcut is not installed:" -ForegroundColor Yellow
    Write-Host $shortcutPath
}

if (-not (Test-Path -LiteralPath $dashboardScript)) {
    throw "Dashboard startup script not found: $dashboardScript"
}

if ($Uninstall) {
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath -Force
        Write-Host "Removed startup shortcut:" -ForegroundColor Green
        Write-Host $shortcutPath
    } else {
        Write-Host "Startup shortcut was not installed:" -ForegroundColor Yellow
        Write-Host $shortcutPath
    }
    return
}

if ($Status) {
    Write-AutostartStatus
    return
}

New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
New-DashboardShortcut `
    -Path $shortcutPath `
    -TargetScript $dashboardScript `
    -WorkingDirectory $scriptDir `
    -Open:$OpenBrowser

Write-Host "Installed startup shortcut:" -ForegroundColor Green
Write-Host $shortcutPath
Write-Host "Target: $dashboardScript"

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
