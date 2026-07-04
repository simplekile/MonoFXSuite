# MonoFX Pipeline Blender — build install ZIP (one command)
# From repo root:  .\tools\fx\monofx_pipeline_blender\build.ps1
# From this dir:   .\build.ps1
# Bump patch:      .\build.ps1 -Bump patch

param(
    [ValidateSet("major", "minor", "patch")]
    [string]$Bump
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Script = Join-Path $Root "scripts\build_release_zip.py"

if (-not (Test-Path $Script)) {
    Write-Error "Build script not found: $Script"
    exit 1
}

$python = $null
foreach ($cmd in @("python", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $python = $cmd
        break
    }
}
if (-not $python) {
    Write-Error "Python not found (install Python or add it to PATH)."
    exit 1
}

$args = @($Script)
if ($Bump) {
    $args += @("--bump", $Bump)
}

Write-Host "Building MonoFX Pipeline Blender..."
& $python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done."
