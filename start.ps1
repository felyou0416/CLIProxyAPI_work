param(
    [ValidateSet('Dashboard', 'GUI')]
    [string]$Mode = 'GUI',
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = $PSScriptRoot
$proxyRoot = Join-Path $workspaceRoot 'CLIProxyAPI'
$storageDir = Join-Path $proxyRoot 'storage'
$dashboardRoot = Join-Path $workspaceRoot 'CLIProxyAPI-Dashboard'

if (-not (Test-Path -LiteralPath $proxyRoot)) {
    throw "CLIProxyAPI runtime directory was not found: $proxyRoot"
}

$env:CLIPROXYAPI_ROOT = $proxyRoot
$env:CLIPROXYAPI_STORAGE_DIR = $storageDir
$env:RELAYX_STORAGE_DIR = $storageDir

switch ($Mode) {
    'Dashboard' {
        & (Join-Path $dashboardRoot 'start.ps1') -OpenBrowser:$OpenBrowser -RestartExisting
        break
    }
    'GUI' {
        & (Join-Path $dashboardRoot 'start.ps1') -RestartExisting
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        $gui = Join-Path $workspaceRoot 'apps\tauri-gui\src-tauri\target\release\cliproxyapi-tauri.exe'
        if (-not (Test-Path -LiteralPath $gui)) {
            throw "Tauri GUI has not been built. Run: cd apps\tauri-gui; npm run build:windows"
        }
        $env:CLIPROXYAPI_REUSE_EXISTING_DASHBOARD = '1'
        Start-Process -FilePath $gui | Out-Null
        break
    }
}
