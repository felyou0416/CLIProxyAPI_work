param(
    [switch]$SkipTests,
    [string]$Output = (Join-Path $PSScriptRoot 'cli-claude-adapter.exe')
)

$ErrorActionPreference = 'Stop'
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)

Push-Location $PSScriptRoot
try {
    if (-not $SkipTests) {
        go test ./...
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    go build -o $resolvedOutput .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "Built: $resolvedOutput"
