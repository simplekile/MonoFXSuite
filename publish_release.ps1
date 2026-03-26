# MonoFX Suite — publish GitHub Release
# Chạy từ repo root. Cần: VERSION đã đúng, đã build installer, đã tag và push tag.
# Prerequisite: GitHub CLI (gh), đã gh auth login

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
$ChangelogPath = Join-Path $ProjectRoot "docs\changelog.md"
$ExePath = Join-Path $ProjectRoot "build\output\MonoFXSuite_Setup.exe"

if (-not (Test-Path $VersionFile)) {
    Write-Error "Không tìm thấy file VERSION tại: $VersionFile"
    exit 1
}

$Version = (Get-Content $VersionFile -Raw).Trim()
$Tag = "v$Version"

# Kiểm tra tag đã tồn tại và đã push
$tagExists = git tag -l $Tag 2>$null
if (-not $tagExists) {
    Write-Host "Tag $Tag chưa tồn tại. Tạo và push tag trước:"
    Write-Host "  git tag -a $Tag -m `"Release $Tag`""
    Write-Host "  git push origin $Tag"
    exit 1
}

# Release notes: prefer RELEASE_NOTES.md (from bump_version), else extract from changelog
$ReleaseNotesPath = Join-Path $ProjectRoot "RELEASE_NOTES.md"
$Notes = "Release $Tag`n`n"
if (Test-Path $ReleaseNotesPath) {
    $notesContent = (Get-Content $ReleaseNotesPath -Raw).Trim()
    if ($notesContent) {
        $Notes = $notesContent + "`n"
    }
}
if ($Notes -eq "Release $Tag`n`n" -and (Test-Path $ChangelogPath)) {
    $content = Get-Content $ChangelogPath -Raw
    $verEscaped = [regex]::Escape($Version)
    $pattern = "(?s)## \[$verEscaped\][^\r\n]*(.*?)(?=\r?\n## |\z)"
    $m = [regex]::Match($content, $pattern)
    if ($m.Success) {
        $Notes = $m.Value.Trim() + "`n"
    }
}

$NotesPath = [System.IO.Path]::GetTempFileName() + ".md"
try {
    # UTF-8 no BOM so GitHub displays the body correctly
    [System.IO.File]::WriteAllText($NotesPath, $Notes, [System.Text.UTF8Encoding]::new($false))

    if (-not (Test-Path $ExePath)) {
        Write-Error "Installer not found. Run .\build\build.ps1 first."
        exit 1
    }

    Write-Host "Creating GitHub Release: $Tag"
    # --notes-file must be absolute path on Windows for gh to read correctly
    $NotesPathFull = [System.IO.Path]::GetFullPath($NotesPath)
    gh release create $Tag --notes-file $NotesPathFull $ExePath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Release may already exist. Try: gh release delete $Tag then run again."
        exit 1
    }
    $url = "https://github.com/simplekile/MonoFXSuite/releases/tag/" + $Tag
    Write-Host "Done. Release: $url"
}
finally {
    if (Test-Path $NotesPath) { Remove-Item $NotesPath -Force }
}
