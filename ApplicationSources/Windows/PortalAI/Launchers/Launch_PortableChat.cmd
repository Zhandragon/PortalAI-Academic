@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
if not exist "%ROOT%Runtime\BootstrapPython\pythonw.exe" (
  echo ERROR: PortableAI BootstrapPython is missing.
  pause
  exit /b 2
)
if not exist "%ROOT%ControlCenter\native_chat.py" (
  echo ERROR: ControlCenter\native_chat.py is missing.
  pause
  exit /b 3
)
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "PATH=%ROOT%Runtime\BootstrapPython;%PATH%"
start "PortableAI Chat" /D "%ROOT%" "%ROOT%Runtime\BootstrapPython\pythonw.exe" -I "%ROOT%ControlCenter\native_chat.py" --root "%ROOT%"
exit /b 0
