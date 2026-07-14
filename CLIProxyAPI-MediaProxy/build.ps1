param(
    [switch]$SkipTests,
    [string]$Output = (Join-Path $PSScriptRoot 'cli-media-proxy.exe')
)

$ErrorActionPreference = 'Stop'

Push-Location $PSScriptRoot
try {
    if (-not $SkipTests) {
        go test ./...
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    go build -o $Output .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "Built: $Output"
