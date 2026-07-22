param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Resolve-Zig {
    $command = Get-Command zig -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $packageRoot) {
        $candidate = Get-ChildItem -Path $packageRoot -Filter zig.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
        if ($candidate) {
            return $candidate
        }
    }
    throw 'Zig was not found. Install it with: winget install --id zig.zig --exact'
}

$zig = Resolve-Zig
$env:CGO_ENABLED = '1'
$env:CC = "$zig cc -target x86_64-windows-gnu"
$outputDir = Join-Path $Root 'dist\windows-amd64'
$output = Join-Path $outputDir 'cliproxy-local.dll'
$header = Join-Path $outputDir 'cliproxy-local.h'

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Push-Location $Root
try {
    if (-not $SkipTests) {
        go test .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    go build -buildmode=c-shared -o $output .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (Test-Path -LiteralPath $header) {
        Remove-Item -LiteralPath $header -Force
    }
} finally {
    Pop-Location
}

Write-Host "Built: $output"
