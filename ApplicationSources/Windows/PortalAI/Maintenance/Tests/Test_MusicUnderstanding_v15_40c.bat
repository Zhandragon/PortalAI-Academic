@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PortableAI Music Understanding v15.40c Test
set "LOG=%~dp0Test_MusicUnderstanding_v15_40c.log"
> "%LOG%" echo PortableAI Music Understanding v15.40c Test
where python.exe >nul 2>&1
if errorlevel 1 goto fail
for /f "delims=" %%P in ('where python.exe') do (
  set "PY=%%P"
  goto found
)
:found
"%PY%" "%~dp0test_music_understanding_v15_40c.py" >>"%LOG%" 2>&1
if errorlevel 1 goto fail
type "%LOG%"
echo.
echo TEST PASSED.
pause
exit /b 0
:fail
echo.
echo TEST FAILED. Log:
echo   %LOG%
type "%LOG%"
pause
exit /b 1
