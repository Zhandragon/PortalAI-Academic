@echo off
setlocal
"%~dp0..\Runtime\BootstrapPython\python.exe" -B -I "%~dp0..\Tools\recover_profile_login.py"
pause
