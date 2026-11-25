@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-setup.ps1" %*
set "result=%errorlevel%"
if not "%result%"=="0" echo Setup preparation did not finish. Review the error above.
pause
exit /b %result%
