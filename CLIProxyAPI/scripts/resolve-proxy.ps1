# Returns path to source-built cli-proxy-api.exe; builds if missing.
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$override = $env:RELAYX_CLI_BINARY
if ($override -and (Test-Path $override)) {
    return (Resolve-Path $override).Path
}

$bin = Join-Path $ProjectRoot "CLIProxyAPI\bin\cli-proxy-api.exe"
if (-not (Test-Path $bin)) {
    & (Join-Path $ProjectRoot "scripts\build-proxy.ps1")
}
if (-not (Test-Path $bin)) {
    throw "Proxy binary not found after build: $bin"
}
return (Resolve-Path $bin).Path
