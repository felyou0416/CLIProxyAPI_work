# Build CLIProxyAPI from upstream source (no prebuilt app/cli-proxy-api.exe).
param(
    [switch]$SkipTidy
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $projectRoot "CLIProxyAPI"
$binDir = Join-Path $srcDir "bin"
$outFile = Join-Path $binDir "cli-proxy-api.exe"

if (-not (Test-Path (Join-Path $srcDir "go.mod"))) {
    Write-Error "Upstream source not found: $srcDir. Run: git clone https://github.com/router-for-me/CLIProxyAPI.git CLIProxyAPI"
}

if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Error "Go is not installed or not on PATH. Install Go 1.26+ from https://go.dev/dl/"
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Push-Location $srcDir
try {
    if (-not $SkipTidy) {
        go mod tidy
    }
    go build -o $outFile ./cmd/server
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "Built: $outFile"
