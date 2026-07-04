@echo off
REM MonoFX Pipeline Blender — build install ZIP (one command)
REM From repo root:  tools\fx\monofx_pipeline_blender\build.bat
REM From this dir:   build.bat
REM Bump patch:      build.bat --bump patch

setlocal
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%scripts\build_release_zip.py"

if not exist "%SCRIPT%" (
    echo Build script not found: %SCRIPT%
    exit /b 1
)

where python >nul 2>&1
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        set "PY=py"
    ) else (
        echo Python not found. Install Python or add it to PATH.
        exit /b 1
    )
)

echo Building MonoFX Pipeline Blender...
"%PY%" "%SCRIPT%" %*
if errorlevel 1 exit /b 1

echo Done.
exit /b 0
