@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Diagnose_PortableAI.ps1" %*
echo.
pause
