# MonoFX Suite - publish GitHub Release
# Run from the repo root. Needs: VERSION right, installer built, tag created and pushed.
# Keep this file ASCII: PowerShell 5.1 reads a file without BOM as ANSI, and Vietnamese text inside a string
# turned into quote marks that swallowed the lines setting the release notes (empty notes v0.1.24-v0.1.31).
# Prerequisite: GitHub CLI (gh), gh auth login done

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
$ChangelogPath = Join-Path $ProjectRoot "docs\changelog.md"
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
    Write-Error "VERSION file not found: $VersionFile"
    exit 1
}

$Version = (Get-Content $VersionFile -Raw -Encoding UTF8).Trim()
$Tag = "v$Version"

# The tag must exist (and be pushed)
$tagExists = git tag -l $Tag 2>$null
if (-not $tagExists) {
    Write-Host "Tag $Tag does not exist. Create and push it first:"
    Write-Host "  git tag -a $Tag -m `"Release $Tag`""
    Write-Host "  git push origin $Tag"
    exit 1
}

# Release notes: prefer RELEASE_NOTES.md (from bump_version), else extract from changelog
$ReleaseNotesPath = Join-Path $ProjectRoot "RELEASE_NOTES.md"
$Notes = "Release $Tag`n`n"
if (Test-Path $ReleaseNotesPath) {
    $notesContent = (Get-Content $ReleaseNotesPath -Raw -Encoding UTF8).Trim()
    if ($notesContent) {
        $Notes = $notesContent + "`n"
    }
}
if ($Notes -eq "Release $Tag`n`n" -and (Test-Path $ChangelogPath)) {
    $content = Get-Content $ChangelogPath -Raw -Encoding UTF8
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

    $BlenderZipPath = Get-BlenderAddonZipPath
    if (-not $BlenderZipPath) {
        Write-Error "Blender add-on ZIP not found in build\output. Run .\build\build.ps1 (builds installer + Blender ZIP)."
        exit 1
    }

    Write-Host "Creating GitHub Release: $Tag"
    Write-Host "Assets: MonoFXSuite_Setup.exe, $(Split-Path $BlenderZipPath -Leaf)"
    # --notes-file must be absolute path on Windows for gh to read correctly
    $NotesPathFull = [System.IO.Path]::GetFullPath($NotesPath)
    # Create with the notes only, then upload the assets: created together, gh left the body empty
    # (v0.1.24, v0.1.25, v0.1.29, v0.1.30), and an edit straight after did not stick either.
    gh release create $Tag --title $Tag --notes-file $NotesPathFull
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Release may already exist. Try: gh release delete $Tag then run again."
        exit 1
    }
    gh release upload $Tag $ExePath $BlenderZipPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Asset upload failed: gh release upload $Tag `"$ExePath`" `"$BlenderZipPath`" --clobber"
        exit 1
    }
    # Check the body; set it again (a few tries, GitHub can lag) if it came out empty
    $bodyLength = 0
    for ($i = 0; $i -lt 4; $i++) {
        if ($i -gt 0) {
            Start-Sleep -Seconds 3
            gh release edit $Tag --notes-file $NotesPathFull | Out-Null
            Start-Sleep -Seconds 2
        }
        $bodyLength = gh release view $Tag --json body --jq ".body | length"
        if ($LASTEXITCODE -eq 0 -and [int]$bodyLength -gt 0) { break }
    }
    if ([int]$bodyLength -eq 0) { Write-Host "Release notes are still empty: gh release edit $Tag --notes-file RELEASE_NOTES.md" }
    $url = "https://github.com/simplekile/MonoFXSuite/releases/tag/" + $Tag
    Write-Host "Done. Release: $url"
}
finally {
    if (Test-Path $NotesPath) { Remove-Item $NotesPath -Force }
}
