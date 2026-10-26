@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
call "%ROOT%\Force_Stop_PortableAI.bat"
