@echo off
setlocal
cd /d "%~dp0"
title PortableAI Open WebUI - Local
set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
  echo ERROR: Open WebUI runtime not installed. Run Install_OpenWebUI_Remote_v15_42.bat first.
  pause
  exit /b 1
)
"%PY%" "%~dp0portal_manager.py" local
if errorlevel 1 (
  echo.
  echo FAILED.
  pause
  exit /b 1
)
echo.
pause
