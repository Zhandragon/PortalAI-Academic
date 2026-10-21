@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0Runtime\Python\pythonw.exe" -B -I "%~dp0app\recovery_ui.py"
