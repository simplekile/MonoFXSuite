# MonoFX Suite - Bump version and update changelog for release
# Usage: .\bump_version.ps1 <major|minor|patch>
# Run from repo root. Updates VERSION and docs/changelog.md.

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("major","minor","patch")]
    [string]$Bump
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
$ChangelogPath = Join-Path $ProjectRoot "docs\changelog.md"

if (-not (Test-Path $VersionFile)) {
    Write-Error "VERSION file not found at $VersionFile"
    exit 1
}

$current = (Get-Content $VersionFile -Raw).Trim()
$parts = $current -split '\.'
if ($parts.Count -lt 3) {
    Write-Error "VERSION must be MAJOR.MINOR.PATCH (e.g. 0.1.0)"
    exit 1
}

$major = [int]$parts[0]
$minor = [int]$parts[1]
$patch = [int]$parts[2]

switch ($Bump) {
    "major" { $major += 1; $minor = 0; $patch = 0 }
    "minor" { $minor += 1; $patch = 0 }
    "patch" { $patch += 1 }
}

$newVersion = "$major.$minor.$patch"
Set-Content -Path $VersionFile -Value $newVersion -NoNewline
Write-Host "VERSION: $current -> $newVersion"

# Update changelog: insert new section after [Unreleased]
if (-not (Test-Path $ChangelogPath)) {
    Write-Host "Changelog not found, skip."
    exit 0
}

$date = Get-Date -Format "yyyy-MM-dd"
$content = Get-Content $ChangelogPath -Raw

# Find "## [Unreleased]" and content until next "## " or end
$pattern = '(?s)(## \[Unreleased\]\r?\n)(.*?)(?=\r?\n## |\z)'
$m = [regex]::Match($content, $pattern)
if (-not $m.Success) {
    Write-Host "Could not find [Unreleased] section in changelog."
    exit 1
}

$unreleasedHeader = $m.Groups[1].Value
$unreleasedBody = $m.Groups[2].Value.Trim()

# New section for this version (keep Unreleased body as release notes)
$nl = "`n"
$newSection = "## [$newVersion] - $date$nl$nl"
if ($unreleasedBody) {
    $newSection += $unreleasedBody + "$nl$nl"
} else {
    $newSection += "### Changes$nl- (describe changes)$nl$nl"
}

# Replace: keep [Unreleased] then add new section; clear Unreleased body
$replacement = $unreleasedHeader + $nl + $nl + $newSection
$newContent = $content -replace [regex]::Escape($m.Value), $replacement

[System.IO.File]::WriteAllText($ChangelogPath, $newContent.TrimEnd(), [System.Text.UTF8Encoding]::new($false))
Write-Host "Changelog: added section [$newVersion] - $date"

# Write release notes for this version (used by publish_release.ps1 for GitHub Release body)
$ReleaseNotesPath = Join-Path $ProjectRoot "RELEASE_NOTES.md"
[System.IO.File]::WriteAllText($ReleaseNotesPath, $newSection.Trim(), [System.Text.UTF8Encoding]::new($false))
Write-Host "Release notes: $ReleaseNotesPath (edit if needed before publish)"

Write-Host "Next: edit docs/changelog.md or RELEASE_NOTES.md if needed, then build, commit, tag, publish."
