@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\Runtime\BootstrapPython\python.exe"
if not exist "%PY%" (
  echo ERROR: PortableAI BootstrapPython is missing: "%PY%" 1>&2
  exit /b 3
)
rem v15.89: BootstrapPython is the orchestration executable only.
rem NEVER export PYTHONHOME here; child component Pythons must find their own stdlib.
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "__PYVENV_LAUNCHER__="
set "PYTHONNOUSERSITE=1"
if not exist "%ROOT%\Agent\.runtime\tmp" mkdir "%ROOT%\Agent\.runtime\tmp" >nul 2>&1
set "TEMP=%ROOT%\Agent\.runtime\tmp"
set "TMP=%TEMP%"
"%PY%" %*
exit /b %ERRORLEVEL%
