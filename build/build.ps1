# MonoFX Suite - build installer
# Run from the project root: .\build\build.ps1
# or from build: .\build.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$IssPath = Join-Path $ProjectRoot "build\installer\MonoFXSuite.iss"
$OutputDir = Join-Path $ProjectRoot "build\output"

$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    Write-Error "Inno Setup not found: $Iscc"
    exit 1
}

if (-not (Test-Path $IssPath)) {
    Write-Error "Installer script not found: $IssPath"
    exit 1
}

$VersionFile = Join-Path $ProjectRoot "VERSION"
$Version = "0.1.0"
if (Test-Path $VersionFile) {
    $Version = (Get-Content $VersionFile -Raw -Encoding UTF8).Trim()
}
Write-Host "Version: $Version"

# The Blender add-on's own build first: it vendors monofx_pipeline_common into the add-on folder, which the
# installer ships (task "blenderaddon" copies it into each Blender 5.0+ and enables it). A release ships only the
# installer (the add-on ZIP is no longer published): the add-on checks the suite's version, stamped here.
$BlenderBuild = Join-Path $ProjectRoot "tools\fx\monofx_pipeline_blender\build.ps1"
if (Test-Path $BlenderBuild) {
    Write-Host "Preparing the Blender add-on..."
    & $BlenderBuild
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$AddonDir = Join-Path $ProjectRoot "tools\fx\monofx_pipeline_blender\monofx_pipeline_blender"
[System.IO.File]::WriteAllText((Join-Path $AddonDir "SUITE_VERSION"), $Version, [System.Text.UTF8Encoding]::new($false))

Write-Host "Building MonoFX Suite installer..."
& $Iscc "/DMyAppVersion=$Version" $IssPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Exe = Join-Path $OutputDir "MonoFXSuite_Setup.exe"
if (Test-Path $Exe) {
    Write-Host "Done. Output: $Exe"
} else {
    Write-Host "Build finished. Check: $OutputDir"
}
