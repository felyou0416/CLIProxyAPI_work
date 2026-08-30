param(
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)

$ErrorActionPreference = 'Stop'
$tauriRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$resourceRoot = Join-Path $tauriRoot 'src-tauri\resources'
$dashboardDist = Join-Path $WorkspaceRoot 'CLIProxyAPI-Dashboard\dist\dashboard'
$dashboardSource = Join-Path $WorkspaceRoot 'CLIProxyAPI-Dashboard'
$required = @(
    @{ Source = Join-Path $dashboardDist 'dashboard.exe'; Target = 'dashboard\dashboard.exe' },
    @{ Source = Join-Path $WorkspaceRoot 'CLIProxyAPI\CLIProxyAPI\bin\cli-proxy-api.exe'; Target = 'cli-proxy-api.exe' },
    @{ Source = Join-Path $WorkspaceRoot 'CLIProxyAPI-AccessGateway\cli-access-gateway.exe'; Target = 'CLIProxyAPI-AccessGateway\cli-access-gateway.exe' },
    @{ Source = Join-Path $WorkspaceRoot 'CLIProxyAPI-MediaProxy\cli-media-proxy.exe'; Target = 'CLIProxyAPI-MediaProxy\cli-media-proxy.exe' },
    @{ Source = Join-Path $WorkspaceRoot 'CLIProxyAPI-MediaProxy\config.example.json'; Target = 'CLIProxyAPI-MediaProxy\config.example.json' },
    @{ Source = Join-Path $WorkspaceRoot 'CLIProxyAPI-LocalPlugin\dist\windows-amd64\cliproxy-local.dll'; Target = 'plugins\cliproxy-local.dll' }
)

foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item.Source)) {
        throw "Required build output not found: $($item.Source)"
    }
}

if (Test-Path $resourceRoot) {
    Remove-Item $resourceRoot -Recurse -Force
}
New-Item $resourceRoot -ItemType Directory -Force | Out-Null
Copy-Item $dashboardDist (Join-Path $resourceRoot 'dashboard') -Recurse -Force
foreach ($item in $required | Select-Object -Skip 1) {
    $target = Join-Path $resourceRoot $item.Target
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item $item.Source $target -Force
}

Write-Host "Staged Tauri Windows resources at $resourceRoot"
