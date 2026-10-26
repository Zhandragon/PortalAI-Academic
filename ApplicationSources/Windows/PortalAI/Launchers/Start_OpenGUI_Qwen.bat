@echo off
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN
for %%# in ("%~dp0..") do set "_PAI_ROOT=%%~f#"
if exist "%_PAI_ROOT%\Runtime\BootstrapPython\python.exe" set "PATH=%_PAI_ROOT%\Runtime\BootstrapPython;%PATH%"
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_END
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" /b pythonw.exe "%~dp0Start_PortableAI_Controller.py" --root "%ROOT%"
    exit /b 0
)
where python.exe >nul 2>&1
if not errorlevel 1 (
    start "" /b python.exe "%~dp0Start_PortableAI_Controller.py" --root "%ROOT%"
    exit /b 0
)
echo ERROR: Python was not found on PATH.
pause
exit /b 2
