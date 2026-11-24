@echo off
setlocal
rem Resolve the bundled interpreter from current and older portable layouts.
set "PORTALAI_SETUP_PYTHON=%~dp0..\..\..\PortalAI-Projection\Runtime\Python\python.exe"
if not exist "%PORTALAI_SETUP_PYTHON%" set "PORTALAI_SETUP_PYTHON=%~dp0..\..\PortalAI-Projection\Runtime\Python\python.exe"
if not exist "%PORTALAI_SETUP_PYTHON%" set "PORTALAI_SETUP_PYTHON=%~dp0..\Runtime\Python\python.exe"
if not exist "%PORTALAI_SETUP_PYTHON%" (
  echo Bundled Python was not found. Keep PortalAI HA Setup beside PortalAI-Projection.
  echo For a standalone HA extraction, use install.sh from a trusted HA terminal.
  exit /b 1
)
if "%~1"=="" (
  "%PORTALAI_SETUP_PYTHON%" -B -I "%~dp0install.py" wizard
) else (
  "%PORTALAI_SETUP_PYTHON%" -B -I "%~dp0install.py" %*
)
set "PORTALAI_SETUP_RESULT=%ERRORLEVEL%"
if not "%PORTALAI_SETUP_RESULT%"=="0" echo Installation did not complete. See README_FIRST.txt and the error above.
if "%~1"=="" pause
exit /b %PORTALAI_SETUP_RESULT%
