# CLIProxyAPI Dashboard — 独立面板项目
param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$envFile = Join-Path $here '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or $line -notmatch '=') { return }
        $k, $v = $line.Split('=', 2)
        $k = $k.Trim()
        $v = $v.Trim().Trim('"').Trim("'")
        if ($k -and -not [Environment]::GetEnvironmentVariable($k)) {
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}
$proxyRoot = $env:CLIPROXYAPI_ROOT
if (-not $proxyRoot) {
    $proxyRoot = Join-Path (Split-Path -Parent $here) 'CLIProxyAPI'
}
Write-Host "Dashboard: $here"
Write-Host "Proxy project (CLIPROXYAPI_ROOT): $proxyRoot"
& (Join-Path $here 'start_dashboard.ps1') @PSBoundParameters
