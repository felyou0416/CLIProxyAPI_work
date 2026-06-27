# Dynamic Upstream Upgrade and Customization Applicator for CLIProxyAPI (CPA)
#
# This script automates syncing from the upstream repository, applying your
# customizations patch, and building the binary.
# It helps you preserve custom modifications across updates effortlessly.

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Starting Upstream Update and Build" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Fetch latest upstream tags/commits
Write-Host "`n[1/4] Fetching latest upstream updates..." -ForegroundColor Yellow
if (-not (git remote | Select-String -Pattern "upstream-cpa")) {
    Write-Host "Upstream remote not found. Adding default upstream remote 'upstream-cpa'..." -ForegroundColor Gray
    git remote add upstream-cpa https://github.com/router-for-me/CLIProxyAPI.git
}
git fetch upstream-cpa --tags

# 2. Check if git working directory is clean
$status = git status --porcelain
if ($status) {
    Write-Host "WARNING: You have uncommitted changes in your working tree." -ForegroundColor Red
    Write-Host "Please commit or stash your changes before running the upgrade." -ForegroundColor Red
    Exit 1
}

# 3. Prompt user for the target tag/commit to upgrade to
Write-Host "`n[2/4] Select target version to merge." -ForegroundColor Yellow
$latestTag = git tag -l "v7.*" | Select-Object -Last 1
Write-Host "Latest available tag upstream is: $latestTag" -ForegroundColor Gray
$targetVersion = Read-Host "Enter target version to merge (default: $latestTag)"
if ([string]::IsNullOrWhiteSpace($targetVersion)) {
    $targetVersion = $latestTag
}

Write-Host "Merging $targetVersion into your branch..." -ForegroundColor Gray
try {
    # Perform standard merge (allowing unrelated histories if needed)
    git merge $targetVersion --allow-unrelated-histories -m "Sync upstream version $targetVersion"
} catch {
    Write-Host "Merge conflict encountered. Please resolve the conflicts and commit, then run this script again." -ForegroundColor Red
    Exit 1
}

# 4. Apply customizations patch
Write-Host "`n[3/4] Applying customizations patch..." -ForegroundColor Yellow
if (Test-Path "customizations.patch") {
    try {
        git apply --reject --whitespace=fix customizations.patch
        Write-Host "Customizations patch successfully applied!" -ForegroundColor Green
    } catch {
        Write-Host "Patch failed to apply cleanly. Conflict files (.rej) have been created." -ForegroundColor Red
        Write-Host "Please manually review the .rej files, apply the changes, and update customizations.patch." -ForegroundColor Red
        Exit 1
    }
} else {
    Write-Host "customizations.patch not found. Skipping patch application." -ForegroundColor Gray
}

# 5. Build binary
Write-Host "`n[4/4] Building Go binary..." -ForegroundColor Yellow
if (Test-Path "CLIProxyAPI\start.ps1") {
    Push-Location "CLIProxyAPI"
    try {
        .\start.ps1 build
        Write-Host "Compilation successful!" -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "CPA start.ps1 script not found. Please compile manually." -ForegroundColor Red
    Exit 1
}

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host " CPA Upgraded & Customizations Applied Successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
