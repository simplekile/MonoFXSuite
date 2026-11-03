# MonoFX Suite — publish GitHub Release
# Chạy từ repo root. Cần: VERSION đã đúng, đã build installer, đã tag và push tag.
# Prerequisite: GitHub CLI (gh), đã gh auth login
# File này phải lưu UTF-8 *có BOM*: không có BOM, Windows PowerShell 5.1 đọc nó là cp1252, chữ "ồ"
# (byte 0x93 = “) thành dấu nháy, nuốt cả đoạn đọc RELEASE_NOTES.md => release body rỗng (v0.1.3–v0.1.22).

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
$ChangelogPath = Join-Path $ProjectRoot "docs\changelog.md"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$ExePath = Join-Path $ProjectRoot "build\output\MonoFXSuite_Setup.exe"
$OutputDir = Join-Path $ProjectRoot "build\output"

function Get-BlenderAddonZipPath {
    $zip = Get-ChildItem -Path $OutputDir -Filter "monofx_pipeline_blender_v*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($zip) { return $zip.FullName }
    return $null
}

if (-not (Test-Path $VersionFile)) {
    Write-Error "Không tìm thấy file VERSION tại: $VersionFile"
    exit 1
}

$Version = [System.IO.File]::ReadAllText($VersionFile, $Utf8NoBom).Trim()
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
    $notesContent = [System.IO.File]::ReadAllText($ReleaseNotesPath, $Utf8NoBom).Trim()
    if ($notesContent) {
        $Notes = $notesContent + "`n"
    }
}
if ($Notes -eq "Release $Tag`n`n" -and (Test-Path $ChangelogPath)) {
    $content = [System.IO.File]::ReadAllText($ChangelogPath, $Utf8NoBom)
    $verEscaped = [regex]::Escape($Version)
    $pattern = "(?s)## \[$verEscaped\][^\r\n]*(.*?)(?=\r?\n## |\z)"
    $m = [regex]::Match($content, $pattern)
    if ($m.Success) {
        $Notes = $m.Value.Trim() + "`n"
    }
}

$NotesPath = Join-Path ([System.IO.Path]::GetTempPath()) "monofx_release_notes_$Tag.md"
try {
    # UTF-8 no BOM so GitHub displays the body correctly
    [System.IO.File]::WriteAllText($NotesPath, $Notes, $Utf8NoBom)

    if (-not (Test-Path $ExePath)) {
        Write-Error "Installer not found. Run .\build\build.ps1 first."
        exit 1
    }

    $BlenderZipPath = Get-BlenderAddonZipPath
    if (-not $BlenderZipPath) {
        Write-Error "Blender add-on ZIP not found in build\output. Run .\build\build.ps1 (builds installer + Blender ZIP)."
        exit 1
    }

    Write-Host "Creating GitHub Release: $Tag"
    Write-Host "Assets: MonoFXSuite_Setup.exe, $(Split-Path $BlenderZipPath -Leaf)"
    # --notes-file must be absolute path on Windows for gh to read correctly
    $NotesPathFull = [System.IO.Path]::GetFullPath($NotesPath)
    gh release create $Tag --notes-file $NotesPathFull $ExePath $BlenderZipPath
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
