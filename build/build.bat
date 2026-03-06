@echo off
REM MonoFX Suite — build installer
REM Chạy từ thư mục project root: build\build.bat
REM Hoặc từ build: build.bat

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "SCRIPT=%~dp0installer\MonoFXSuite.iss"

if not exist "%ISCC%" (
    echo Khong tim thay Inno Setup: %ISCC%
    exit /b 1
)
if not exist "%SCRIPT%" (
    echo Khong tim thay script: %SCRIPT%
    exit /b 1
)

echo Building MonoFX Suite installer...
"%ISCC%" "%SCRIPT%"
if errorlevel 1 exit /b 1

echo.
echo Done. Output: %~dp0output\MonoFXSuite_Setup.exe
exit /b 0
