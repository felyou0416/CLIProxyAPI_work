# Start CLIProxyAPI proxy (source build: CLIProxyAPI\bin\cli-proxy-api.exe)
param(
    [ValidateSet('codex', 'dashboard', 'tui')]
    [string]$Mode = 'codex'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$storageDir = Join-Path $Root 'storage'
$exe = & (Join-Path $Root 'scripts\resolve-proxy.ps1') -ProjectRoot $Root

switch ($Mode.ToLower()) {
    'codex' {
        $config = Join-Path $storageDir 'config\base-config.yaml'
        $description = 'Base config'
    }
    'dashboard' {
        $config = Join-Path $storageDir 'runtime\cliproxyapi-active-config.yaml'
        $description = 'Dashboard runtime config'
    }
    'tui' {
        $config = Join-Path $storageDir 'config\base-config.yaml'
        Write-Host "Starting TUI..."
        Push-Location $Root
        try {
            & $exe -tui -standalone -config $config
            exit $LASTEXITCODE
        } finally {
            Pop-Location
        }
    }
}

if (-not (Test-Path $config)) {
    Write-Error "Config not found: $config"
}

Write-Host "CLIProxyAPI - $description"
Write-Host "Binary: $exe"
Write-Host "Config: $config"
Write-Host "URL: http://127.0.0.1:8317"
Push-Location $Root
try {
    & $exe -config $config
} finally {
    Pop-Location
}
