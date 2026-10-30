@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_Qwen3_TTS_Portable.ps1" %*
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Qwen3-TTS installation FAILED with exit code %ERR%.
) else (
  echo Qwen3-TTS installation finished successfully.
)
pause
exit /b %ERR%
