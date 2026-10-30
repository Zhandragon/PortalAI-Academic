@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
"%ROOT%\Runtime\BootstrapPython\python.exe" -B "%ROOT%\Agent\ai_tools.py" voice-design "PortableAI voice system is online." "Natural adult narrator, clear, calm, realistic" --language English
set ERR=%ERRORLEVEL%
pause
exit /b %ERR%
