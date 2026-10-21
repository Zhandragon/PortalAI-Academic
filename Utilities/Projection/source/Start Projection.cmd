@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0Connections\" (mkdir "%~dp0Connections" || exit /b 1)
if not exist "%~dp0state\" (mkdir "%~dp0state" || exit /b 1)
if not exist "%~dp0state\input\" (mkdir "%~dp0state\input" || exit /b 1)
if not exist "%~dp0state\tmp\" (mkdir "%~dp0state\tmp" || exit /b 1)
if not exist "%~dp0state\cache\" (mkdir "%~dp0state\cache" || exit /b 1)
start "" "%~dp0Runtime\Python\pythonw.exe" -B -I "%~dp0app\projection_ui.py"
