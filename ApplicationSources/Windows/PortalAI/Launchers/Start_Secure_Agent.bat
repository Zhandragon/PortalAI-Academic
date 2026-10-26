@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "TARGET=%~dp0Start_Secure_Agent_v15_53.ps1"

if not exist "%TARGET%" (
    echo.
    echo ERROR: Secure Agent PowerShell launcher was not found:
    echo   "%TARGET%"
    echo.
    echo Expected file:
    echo   Start_Secure_Agent_v15_53.ps1
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Secure Agent launcher failed with exit code %RC%.
    echo The PowerShell error above should now identify the failing process.
    echo.
    pause
)

exit /b %RC%
