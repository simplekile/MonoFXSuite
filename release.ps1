# MonoFX Suite — release in two steps (run from the repo root)
#
#   .\release.ps1 prepare [-Bump patch|minor|major]
#       On the branch that goes to main (or main itself). Checks the tree is clean, the tests pass and
#       docs/changelog.md has something under [Unreleased]; then bump_version.ps1 (VERSION, changelog,
#       RELEASE_NOTES.md) and one commit "docs: release vX.Y.Z". Nothing is pushed.
#
#   .\release.ps1 publish [-DryRun]
#       On main as it is on origin (a detached checkout of origin/main works, e.g. in a worktree).
#       Checks everything first, builds the installer and the Blender ZIP, and only then tags HEAD,
#       pushes the tag and creates the GitHub Release (publish_release.ps1). -DryRun stops after the build.
#
# Needs: git, gh (logged in), Python with pytest, Inno Setup 6.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("prepare", "publish")]
    [string]$Step,
    [ValidateSet("major", "minor", "patch")]
    [string]$Bump = "patch",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Fail([string]$Message) {
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Git([string[]]$GitArgs) {
    # Not "Git": PowerShell names are case-blind, so a function Git would call itself for git
    $out = & git.exe @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "git $($GitArgs -join ' ') failed: $out" }
    return ($out | Out-String).Trim()
}

function Assert-Clean {
    $dirty = Invoke-Git @("status", "--porcelain", "--untracked-files=no")
    if ($dirty) { Fail "uncommitted changes:`n$dirty" }
}

function Get-Version { return (Get-Content (Join-Path $Root "VERSION") -Raw -Encoding UTF8).Trim() }

function Get-UnreleasedBody {
    $content = Get-Content (Join-Path $Root "docs\changelog.md") -Raw -Encoding UTF8
    $m = [regex]::Match($content, '(?s)## \[Unreleased\]\r?\n(.*?)(?=\r?\n## |\z)')
    if (-not $m.Success) { Fail "docs/changelog.md has no [Unreleased] section" }
    return $m.Groups[1].Value.Trim()
}

function Invoke-Tests {
    Write-Host "Running tests..."
    & python -m pytest tests -q -p no:cacheprovider 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { Fail "tests failed" }
}

# ---------------------------------------------------------------------------
if ($Step -eq "prepare") {
    Assert-Clean
    if (-not (Get-UnreleasedBody)) {
        Fail "nothing under [Unreleased] in docs/changelog.md: write the release notes there first"
    }
    Invoke-Tests
    $before = Get-Version
    & (Join-Path $Root "bump_version.ps1") $Bump
    if ($LASTEXITCODE -ne 0) { Fail "bump_version.ps1 failed" }
    $version = Get-Version
    if ($version -eq $before) { Fail "VERSION did not change" }
    Invoke-Git @("add", "VERSION", "docs/changelog.md", "RELEASE_NOTES.md") | Out-Null
    Invoke-Git @("commit", "-q", "-m", "docs: release v$version") | Out-Null
    Write-Host ""
    Write-Host "Prepared v$version ($before -> $version), committed. Next: get this commit onto main, then:" -ForegroundColor Green
    Write-Host "  .\release.ps1 publish"
    exit 0
}

# --- publish ---------------------------------------------------------------
$version = Get-Version
$tag = "v$version"
Write-Host "Publishing $tag"

Assert-Clean
Invoke-Git @("fetch", "-q", "origin", "main", "--tags") | Out-Null
$head = Invoke-Git @("rev-parse", "HEAD")
$main = Invoke-Git @("rev-parse", "origin/main")
if ($head -ne $main) { Fail "HEAD is not origin/main ($main). Merge the release commit, then check out origin/main." }

$changelog = Get-Content (Join-Path $Root "docs\changelog.md") -Raw -Encoding UTF8
if ($changelog -notmatch "## \[$([regex]::Escape($version))\]") {
    Fail "docs/changelog.md has no [$version] section: run .\release.ps1 prepare first"
}
if (Invoke-Git @("tag", "-l", $tag)) { Fail "tag $tag already exists locally" }
if (Invoke-Git @("ls-remote", "--tags", "origin", $tag)) { Fail "tag $tag already exists on origin" }
# Windows PowerShell 5.1 turns a native command's stderr into a terminating error under "Stop", so
# a gh that answers "release not found" (the case we want) would stop the script: exit code only.
function Test-Native([scriptblock]$Command) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command *> $null } finally { $ErrorActionPreference = $saved }
    return ($LASTEXITCODE -eq 0)
}
if (-not (Test-Native { gh auth status })) { Fail "gh is not logged in (gh auth login)" }
if (Test-Native { gh release view $tag }) { Fail "GitHub Release $tag already exists" }
if (-not (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe")) { Fail "Inno Setup 6 not found" }

Invoke-Tests

# Build before tagging, so a failed build leaves no tag behind
$start = Get-Date
Write-Host "Building..."
& (Join-Path $Root "build\build.ps1") | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "build failed" }
$exe = Get-Item (Join-Path $Root "build\output\MonoFXSuite_Setup.exe") -ErrorAction SilentlyContinue
$zip = Get-ChildItem (Join-Path $Root "build\output") -Filter "monofx_pipeline_blender_v*.zip" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exe -or $exe.LastWriteTime -lt $start) { Fail "installer was not rebuilt" }
if (-not $zip -or $zip.LastWriteTime -lt $start) { Fail "Blender ZIP was not rebuilt" }
Write-Host "  $($exe.Name) ($([math]::Round($exe.Length / 1MB, 1)) MB), $($zip.Name)"

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run: checks and build passed. Not tagged, nothing pushed or published." -ForegroundColor Yellow
    exit 0
}

Invoke-Git @("tag", "-a", $tag, "-m", "Release $tag") | Out-Null
Invoke-Git @("push", "-q", "origin", $tag) | Out-Null
& (Join-Path $Root "publish_release.ps1")
if ($LASTEXITCODE -ne 0) { Fail "publish_release.ps1 failed (the tag $tag is pushed; fix and run publish_release.ps1 again)" }
Write-Host ""
Write-Host "Released $tag" -ForegroundColor Green
