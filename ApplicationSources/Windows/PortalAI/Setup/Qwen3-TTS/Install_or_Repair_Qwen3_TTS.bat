@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
for %%I in ("%HERE%..\..") do set "ROOT=%%~fI"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%Install_or_Repair_Qwen3_TTS.ps1" -Root "%ROOT%" %*
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Qwen3-TTS install/repair FAILED.
  echo See the error above. Installation logs, when started, are in Agent\.runtime\qwen3_tts_install.log.
) else (
  echo Qwen3-TTS install/repair finished successfully.
)
pause
exit /b %ERR%
