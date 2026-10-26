@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-universal.ps1" %*
if errorlevel 1 pause
