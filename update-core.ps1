param(
    [string]$TargetVersion,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$CorePath = Join-Path $Root 'CLIProxyAPI\CLIProxyAPI'
$VersionFile = Join-Path $Root 'UPSTREAM_VERSION'
$Remote = 'upstream-cpa'
$UpstreamURL = 'https://github.com/router-for-me/CLIProxyAPI.git'

function Invoke-Git([string[]]$Arguments) {
    & git -C $Root @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Sync-Core([string]$Source, [string]$Target) {
    $rootResolved = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $targetResolved = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
    if (-not $targetResolved.StartsWith($rootResolved, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to sync outside workspace: $targetResolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'go.mod'))) {
        throw "Upstream worktree is invalid: $Source"
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    & robocopy $Source $Target /MIR /XD .git /XF .git /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git was not found in PATH.'
}
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw 'Go was not found in PATH.'
}

$remoteNames = & git -C $Root remote
if ($remoteNames -notcontains $Remote) {
    Invoke-Git @('remote', 'add', $Remote, $UpstreamURL)
}

Write-Host '[1/5] Fetching official CPA tags...'
Invoke-Git @('fetch', $Remote, '--tags', '--prune')

if ([string]::IsNullOrWhiteSpace($TargetVersion)) {
    $TargetVersion = & git -C $Root tag -l 'v7.*' --sort=-v:refname | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($TargetVersion)) {
    throw 'No upstream v7 tag was found.'
}
Invoke-Git @('rev-parse', '--verify', "$TargetVersion^{commit}")

$coreStatus = & git -C $Root status --porcelain -- 'CLIProxyAPI/CLIProxyAPI'
if ($coreStatus) {
    throw 'The CPA core has local changes. Commit or restore them before updating.'
}

$previousVersion = if (Test-Path -LiteralPath $VersionFile) {
    (Get-Content -LiteralPath $VersionFile -Raw).Trim()
} else {
    ''
}
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("cliproxyapi-upstream-" + [guid]::NewGuid().ToString('N'))

try {
    Write-Host "[2/5] Syncing pristine core from $TargetVersion..."
    Invoke-Git @('worktree', 'add', '--detach', $tempRoot, $TargetVersion)
    Sync-Core $tempRoot $CorePath

    Write-Host '[3/5] Building and testing core...'
    Push-Location $CorePath
    try {
        if (-not $SkipTests) {
            go test ./...
            if ($LASTEXITCODE -ne 0) { throw 'CPA tests failed.' }
        }
        go build -o (Join-Path $env:TEMP 'cliproxyapi-update-check.exe') ./cmd/server
        if ($LASTEXITCODE -ne 0) { throw 'CPA build failed.' }
    } finally {
        Pop-Location
    }

    Write-Host '[4/5] Building local extensions...'
    & (Join-Path $Root 'CLIProxyAPI-LocalPlugin\build.ps1') -SkipTests:$SkipTests
    if ($LASTEXITCODE -ne 0) { throw 'Local plugin build failed.' }
    & (Join-Path $Root 'CLIProxyAPI-MediaProxy\build.ps1') -SkipTests:$SkipTests
    if ($LASTEXITCODE -ne 0) { throw 'MediaProxy build failed.' }
    if (-not $SkipTests) {
        Push-Location (Join-Path $Root 'CLIProxyAPI-Dashboard')
        try {
            python -m unittest tests.test_runtime_config tests.test_media_proxy_process
            if ($LASTEXITCODE -ne 0) { throw 'Dashboard runtime-config tests failed.' }
        } finally {
            Pop-Location
        }
    }

    Write-Host '[5/5] Recording verified upstream version...'
    Set-Content -LiteralPath $VersionFile -Value $TargetVersion -Encoding ascii
    Write-Host "CPA core updated successfully to $TargetVersion." -ForegroundColor Green
} catch {
    if ($previousVersion -and $previousVersion -ne $TargetVersion) {
        Write-Warning "Update failed. Restoring pristine core $previousVersion..."
        $restoreRoot = Join-Path ([IO.Path]::GetTempPath()) ("cliproxyapi-restore-" + [guid]::NewGuid().ToString('N'))
        try {
            Invoke-Git @('worktree', 'add', '--detach', $restoreRoot, $previousVersion)
            Sync-Core $restoreRoot $CorePath
        } finally {
            if (Test-Path -LiteralPath $restoreRoot) {
                & git -C $Root worktree remove --force $restoreRoot | Out-Null
            }
        }
    }
    throw
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        & git -C $Root worktree remove --force $tempRoot | Out-Null
    }
    & git -C $Root worktree prune | Out-Null
}
