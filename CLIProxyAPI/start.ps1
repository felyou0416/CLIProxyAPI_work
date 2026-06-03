# CLIProxyAPI 代理项目 — 启动入口
param(
    [ValidateSet('build', 'codex', 'dashboard', 'tui', 'help')]
    [string]$Action = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Show-Help {
    Write-Host @"

CLIProxyAPI 代理项目 (CLIProxyAPI_work\CLIProxyAPI)

  .\start.ps1 build       编译 CLIProxyAPI\bin\cli-proxy-api.exe
  .\start.ps1 codex       启动代理 — storage\config\base-config.yaml
  .\start.ps1 dashboard   启动代理 — storage\runtime\cliproxyapi-active-config.yaml
  .\start.ps1 tui         TUI 模式

Dashboard 是独立项目，请到 CLIProxyAPI-Dashboard 目录启动:
  cd ..\CLIProxyAPI-Dashboard
  .\start.ps1

"@
}

switch ($Action) {
    'build' {
        & "$Root\scripts\build-proxy.ps1"
    }
    { $_ -in 'codex', 'dashboard', 'tui' } {
        & "$Root\scripts\start-proxy.ps1" $Action
    }
    default { Show-Help }
}
