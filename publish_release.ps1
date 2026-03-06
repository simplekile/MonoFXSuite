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

# Release notes từ changelog
$Notes = "Release $Tag`n`n"
if (Test-Path $ChangelogPath) {
    $content = Get-Content $ChangelogPath -Raw
    $verEscaped = [regex]::Escape($Version)
    $pattern = "(?s)## \[$verEscaped\][^\r\n]*(.*?)(?=\r?\n## |\z)"
    $m = [regex]::Match($content, $pattern)
    if ($m.Success) {
        $Notes = $m.Value.Trim() + "`n"
    }
}

$NotesPath = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($NotesPath, $Notes, [System.Text.Encoding]::UTF8)

    if (-not (Test-Path $ExePath)) {
        Write-Error "Không tìm thấy installer: $ExePath — chạy .\build\build.ps1 trước."
        exit 1
    }

    Write-Host "Creating GitHub Release: $Tag"
    Write-Host "Notes (excerpt): $($Notes.Substring(0, [Math]::Min(80, $Notes.Length)))..."
    gh release create $Tag --notes-file $NotesPath $ExePath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Nếu release đã tồn tại: gh release delete $Tag (rồi chạy lại) hoặc gh release edit $Tag --notes-file ..."
        exit 1
    }
    Write-Host "Done. Release: https://github.com/simplekile/MonoFXSuite/releases/tag/$Tag"
}
finally {
    if (Test-Path $NotesPath) { Remove-Item $NotesPath -Force }
}
