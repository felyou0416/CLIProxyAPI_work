param(
    [switch]$Apply,
    [switch]$IncludeLogs,
    [switch]$IncludeArchivedErrorLogs,
    [switch]$IncludeBackups,
    [switch]$IncludeGeneratedImages,
    [switch]$IncludeOldAuth,
    [int]$KeepBackupDays = 14,
    [int]$KeepLogDays = 7
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$WorkspaceRoot = Split-Path -Parent $Root
$Storage = Join-Path $Root 'storage'
$Dashboard = Join-Path $WorkspaceRoot 'CLIProxyAPI-Dashboard'

function Get-ItemSize {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) { return [int64]$item.Length }
    return [int64]((Get-ChildItem -LiteralPath $Path -Force -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum)
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[object]]$List,
        [string]$Path,
        [string]$Kind,
        [string]$Reason,
        [string]$Risk
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not ($resolved.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) -or $resolved.StartsWith($Dashboard, [StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing cleanup outside workspace: $resolved"
    }
    $List.Add([pscustomobject]@{
        Kind = $Kind
        Risk = $Risk
        SizeMB = [math]::Round((Get-ItemSize -Path $resolved) / 1MB, 3)
        Path = $resolved
        Reason = $Reason
    }) | Out-Null
}

$candidates = [System.Collections.Generic.List[object]]::new()

Get-ChildItem -LiteralPath (Join-Path $Storage 'runtime\tmp') -Directory -Filter 'auth-test-*' -ErrorAction SilentlyContinue |
    ForEach-Object { Add-Candidate $candidates $_.FullName 'temp' 'Completed authentication test workspace; regenerated for each test.' 'safe' }
if ($IncludeOldAuth) {
    Add-Candidate $candidates (Join-Path $Storage 'old') 'old-auth' 'Old antigravity auth copies; not referenced by current dashboard paths.' 'review'
    Add-Candidate $candidates (Join-Path $Storage 'auth\sources') 'old-auth' 'Legacy auth source staging directory; current sources.json no longer references it.' 'review'
}

if (Test-Path -LiteralPath $Dashboard) {
    Get-ChildItem -LiteralPath $Dashboard -Force -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq '__pycache__' -or $_.Name -eq '.pytest_cache' } |
        ForEach-Object { Add-Candidate $candidates $_.FullName 'cache' 'Python test/import cache; always regenerated.' 'safe' }
}

if ($IncludeLogs) {
    foreach ($path in @(
        (Join-Path $Storage 'logs\request_logs_legacy_from_active_auth_20260518-142145'),
        (Join-Path $Storage 'logs\request_archive'),
        (Join-Path $Storage 'auth\logs')
    )) {
        Add-Candidate $candidates $path 'logs' "Old request/error logs; keep only if you need historical dashboard evidence." 'review'
    }
    $cutoff = (Get-Date).AddDays(-[math]::Abs($KeepLogDays))
    Get-ChildItem -LiteralPath (Join-Path $Storage 'logs') -Force -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff -and ($_.Extension -eq '.log' -or $_.Name -like '*.stdout.log' -or $_.Name -like '*.stderr.log') } |
        ForEach-Object { Add-Candidate $candidates $_.FullName 'logs' "Log older than $KeepLogDays day(s)." 'review' }
}

if ($IncludeArchivedErrorLogs) {
    Add-Candidate $candidates (Join-Path $Storage 'auth\archive\default\metadata\logs') 'archived-error-logs' 'Historical error request logs; dashboard can run without them.' 'review'
}

if ($IncludeBackups) {
    $cutoff = (Get-Date).AddDays(-[math]::Abs($KeepBackupDays))
    Get-ChildItem -LiteralPath (Join-Path $Storage 'backups') -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object { Add-Candidate $candidates $_.FullName 'backup' "Backup older than $KeepBackupDays day(s)." 'review' }
    Add-Candidate $candidates (Join-Path $Storage 'backups\dashboard-runtime-static') 'backup' 'Old copied management.html; current runtime/config static files are kept.' 'review'
}

if ($IncludeGeneratedImages) {
    Add-Candidate $candidates (Join-Path $Storage 'generated-images') 'generated' 'Generated images; remove only if you do not need these outputs.' 'review'
}

if (-not $candidates.Count) {
    Write-Host 'No cleanup candidates found.'
    exit 0
}

($candidates | Sort-Object Risk, Kind, Path | Format-Table Kind, Risk, SizeMB, Path, Reason -AutoSize | Out-String -Width 260).TrimEnd() | Write-Host
$total = ($candidates | Measure-Object SizeMB -Sum).Sum
Write-Host ("Total candidate size: {0:N3} MB" -f $total)

if (-not $Apply) {
    Write-Host 'Preview only. Re-run with -Apply to delete the listed candidates.'
    Write-Host 'Use -IncludeLogs, -IncludeArchivedErrorLogs, -IncludeBackups, -IncludeGeneratedImages, or -IncludeOldAuth to include higher-risk categories.'
    exit 0
}

foreach ($candidate in $candidates) {
    $allowedReview =
        ($candidate.Kind -eq 'logs' -and $IncludeLogs) -or
        ($candidate.Kind -eq 'archived-error-logs' -and $IncludeArchivedErrorLogs) -or
        ($candidate.Kind -eq 'backup' -and $IncludeBackups) -or
        ($candidate.Kind -eq 'generated' -and $IncludeGeneratedImages) -or
        ($candidate.Kind -eq 'old-auth' -and $IncludeOldAuth)
    if ($candidate.Risk -ne 'safe' -and -not $allowedReview) {
        continue
    }
    if (-not (Test-Path -LiteralPath $candidate.Path)) { continue }
    $item = Get-Item -LiteralPath $candidate.Path -Force
    if ($item.PSIsContainer) {
        Remove-Item -LiteralPath $candidate.Path -Recurse -Force
    } else {
        Remove-Item -LiteralPath $candidate.Path -Force
    }
    Write-Host "Deleted: $($candidate.Path)"
}
