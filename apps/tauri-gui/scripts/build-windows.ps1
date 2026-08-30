$ErrorActionPreference = 'Stop'

$vsDevCmd = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsDevCmd)) {
    throw "Visual Studio 2022 Build Tools are required. Install the Desktop development with C++ workload."
}

$vsInstallerDir = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer'
if (Test-Path -LiteralPath $vsInstallerDir) {
    $env:Path = "$vsInstallerDir;$env:Path"
}

$tauriRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$command = "call `"$vsDevCmd`" -arch=x64 -host_arch=x64 && cd /d `"$tauriRoot`" && npm run build"
& cmd.exe /d /s /c $command
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
