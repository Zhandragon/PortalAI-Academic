@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PortableAI Music Understanding v15.40b Test
set "LOG=%~dp0Test_MusicUnderstanding_v15_40b.log"
> "%LOG%" echo PortableAI Music Understanding v15.40b Test
echo PortableAI Music Understanding v15.40b Test
echo.

set "BOOTPY="
where python.exe >nul 2>&1 && set "BOOTPY=python.exe"
if defined BOOTPY goto run_python
where py.exe >nul 2>&1 && goto run_py
echo ERROR: No bootstrap Python found on PATH.>>"%LOG%"
goto fail

:run_python
"%BOOTPY%" "%~dp0test_music_understanding_v15_40b.py" >>"%LOG%" 2>&1
goto result

:run_py
py.exe -3 "%~dp0test_music_understanding_v15_40b.py" >>"%LOG%" 2>&1

:result
if errorlevel 1 goto fail
type "%LOG%"
echo.
echo TEST PASSED.
pause
exit /b 0

:fail
echo.
echo TEST FAILED. Full log:
echo   %LOG%
type "%LOG%"
pause
exit /b 1
