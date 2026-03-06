# MonoFX Suite — build installer
# Chạy từ thư mục project root: .\build\build.ps1
# Hoặc từ build: .\build.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$IssPath = Join-Path $ProjectRoot "build\installer\MonoFXSuite.iss"
$OutputDir = Join-Path $ProjectRoot "build\output"

$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    Write-Error "Không tìm thấy Inno Setup: $Iscc"
    exit 1
}

if (-not (Test-Path $IssPath)) {
    Write-Error "Không tìm thấy script: $IssPath"
    exit 1
}

$VersionFile = Join-Path $ProjectRoot "VERSION"
$Version = "0.1.0"
if (Test-Path $VersionFile) {
    $Version = (Get-Content $VersionFile -Raw).Trim()
}
Write-Host "Version: $Version"

Write-Host "Building MonoFX Suite installer..."
& $Iscc "/DMyAppVersion=$Version" $IssPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Exe = Join-Path $OutputDir "MonoFXSuite_Setup.exe"
if (Test-Path $Exe) {
    Write-Host "Done. Output: $Exe"
} else {
    Write-Host "Build finished. Check: $OutputDir"
}
