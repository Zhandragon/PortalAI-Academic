@echo off
setlocal
for %%I in ("%~dp0..") do set "PORTALAI_REPAIR_ROOT=%%~fI"
"%PORTALAI_REPAIR_ROOT%\Runtime\BootstrapPython\python.exe" -I -B "%PORTALAI_REPAIR_ROOT%\Tools\repair_account_runtime.py" --repair
if errorlevel 1 (
  echo Repair did not finish. Your password and encrypted profiles were not reset.
) else (
  echo Account runtime repaired. Reopen PortalAI and sign in with your usual password.
)
pause
endlocal
