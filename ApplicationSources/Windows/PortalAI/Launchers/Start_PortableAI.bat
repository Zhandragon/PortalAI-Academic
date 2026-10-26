@echo off
setlocal EnableExtensions
title PortableAI - OpenGUI + Qwen

REM ============================================================
REM PortableAI all-in-one launcher - AV-clean startup path
REM Place this BAT in either:
REM   PortableAI\
REM or:
REM   PortableAI\Launchers\
REM
REM v15.28 removes routine PowerShell use. Port checks use netstat,
REM readiness uses Windows curl.exe, and OpenGUI discovery uses CMD
REM + registry queries. Qwen arguments and startup behavior are unchanged.
REM ============================================================

set "HERE=%~dp0"
set "ROOT="

if exist "%HERE%LLM\llamacpp\llama-server.exe" (
    set "ROOT=%HERE:~0,-1%"
)

if not defined ROOT if exist "%HERE%..\LLM\llamacpp\llama-server.exe" (
    for %%I in ("%HERE%..") do set "ROOT=%%~fI"
)

if not defined ROOT (
    echo ============================================================
    echo ERROR: Could not locate the PortableAI root.
    echo.
    echo Expected:
    echo   LLM\llamacpp\llama-server.exe
    echo ============================================================
    pause
    exit /b 1
)

cd /d "%ROOT%"

set "LLAMA=%ROOT%\LLM\llamacpp\llama-server.exe"
set "MODEL=%ROOT%\LLM\models\Qwen3.8-27B-Q4_K_M.gguf"
set "MMPROJ=%ROOT%\LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf"

echo.
echo ============================================================
echo PortableAI
echo Root: %ROOT%
echo ============================================================
echo.

if not exist "%LLAMA%" (
    echo ERROR: llama-server.exe was not found:
    echo   "%LLAMA%"
    pause
    exit /b 1
)

if not exist "%MODEL%" (
    echo ERROR: Qwen model was not found:
    echo   "%MODEL%"
    pause
    exit /b 1
)

if not exist "%MMPROJ%" (
    echo ERROR: multimodal projection was not found:
    echo   "%MMPROJ%"
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM Check whether Qwen is already listening without PowerShell.
REM ------------------------------------------------------------
call :Port8080Listening
if errorlevel 1 (
    echo [START] Starting Qwen / llama.cpp...

    REM Record the exact launch command for validated VRAM-handoff recovery.
    if not exist "%ROOT%\Agent\.runtime" mkdir "%ROOT%\Agent\.runtime" >nul 2>&1
    > "%ROOT%\Agent\.runtime\qwen_launch_command.txt" echo "%LLAMA%" -m "%MODEL%" --mmproj "%MMPROJ%" -ngl 999 -c 16384 --host 127.0.0.1 --port 8080
    > "%ROOT%\Agent\.runtime\qwen_launch_executable.txt" echo %LLAMA%

    start "PortableAI - Qwen" /D "%ROOT%" "%LLAMA%" ^
      -m "%MODEL%" ^
      --mmproj "%MMPROJ%" ^
      -ngl 999 ^
      -c 16384 ^
      --host 127.0.0.1 ^
      --port 8080

    echo [WAIT] Waiting for Qwen to become ready...
    call :WaitForQwen
    if errorlevel 1 (
        echo.
        echo ERROR: Qwen did not become ready on port 8080 within 5 minutes.
        echo Check the Qwen console window for the actual error.
        pause
        exit /b 1
    )

    echo [OK] Qwen is ready.
) else (
    echo [OK] Qwen is already running on port 8080.
)

REM ------------------------------------------------------------
REM Locate and launch OpenGUI without PowerShell.
REM ------------------------------------------------------------
echo [START] Looking for OpenGUI...
call :LaunchOpenGUI
if errorlevel 2 (
    echo.
    echo [WARN] Qwen is running, but OpenGUI could not be located automatically.
    echo OpenGUI can still be opened manually.
    echo.
    pause
    exit /b 2
)

echo.
echo ============================================================
echo PortableAI is ready.
echo Qwen:    http://127.0.0.1:8080
echo OpenGUI: launched
echo ============================================================
timeout /t 3 /nobreak >nul
exit /b 0

REM ============================================================
REM Helpers
REM ============================================================

:Port8080Listening
netstat -ano -p tcp 2>nul | findstr /R /C:":8080 .*LISTENING" >nul
exit /b %errorlevel%

:WaitForQwen
setlocal
set /a _PAI_WAIT_COUNT=0
where curl.exe >nul 2>&1
if errorlevel 1 goto WaitForQwenPortOnly

:WaitForQwenHttpLoop
curl.exe -fsS --max-time 3 "http://127.0.0.1:8080/v1/models" >nul 2>&1
if not errorlevel 1 endlocal & exit /b 0
set /a _PAI_WAIT_COUNT+=1
if %_PAI_WAIT_COUNT% GEQ 150 endlocal & exit /b 1
timeout /t 2 /nobreak >nul
goto WaitForQwenHttpLoop

:WaitForQwenPortOnly
call :Port8080Listening
if not errorlevel 1 endlocal & exit /b 0
set /a _PAI_WAIT_COUNT+=1
if %_PAI_WAIT_COUNT% GEQ 150 endlocal & exit /b 1
timeout /t 2 /nobreak >nul
goto WaitForQwenPortOnly

:LaunchOpenGUI
setlocal
set "OPENGUI_EXE="

if exist "%LOCALAPPDATA%\Programs\OpenGUI\OpenGUI.exe" set "OPENGUI_EXE=%LOCALAPPDATA%\Programs\OpenGUI\OpenGUI.exe"
if not defined OPENGUI_EXE if exist "%LOCALAPPDATA%\OpenGUI\OpenGUI.exe" set "OPENGUI_EXE=%LOCALAPPDATA%\OpenGUI\OpenGUI.exe"
if not defined OPENGUI_EXE if exist "%ProgramFiles%\OpenGUI\OpenGUI.exe" set "OPENGUI_EXE=%ProgramFiles%\OpenGUI\OpenGUI.exe"
if not defined OPENGUI_EXE if not "%ProgramFiles(x86)%"=="" if exist "%ProgramFiles(x86)%\OpenGUI\OpenGUI.exe" set "OPENGUI_EXE=%ProgramFiles(x86)%\OpenGUI\OpenGUI.exe"

if not defined OPENGUI_EXE for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe" /ve 2^>nul ^| findstr /I "REG_SZ"') do set "OPENGUI_EXE=%%B"
if not defined OPENGUI_EXE for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe" /ve 2^>nul ^| findstr /I "REG_SZ"') do set "OPENGUI_EXE=%%B"
if not defined OPENGUI_EXE for /f "delims=" %%I in ('where OpenGUI.exe 2^>nul') do if not defined OPENGUI_EXE set "OPENGUI_EXE=%%~fI"

if defined OPENGUI_EXE if exist "%OPENGUI_EXE%" (
    start "" "%OPENGUI_EXE%"
    echo [OK] OpenGUI: %OPENGUI_EXE%
    endlocal & exit /b 0
)

REM Shortcut search is intentionally last because it is slower than direct paths.
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs" for /r "%APPDATA%\Microsoft\Windows\Start Menu\Programs" %%I in (*OpenGUI*.lnk) do if not defined OPENGUI_EXE set "OPENGUI_EXE=%%~fI"
if not defined OPENGUI_EXE if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs" for /r "%ProgramData%\Microsoft\Windows\Start Menu\Programs" %%I in (*OpenGUI*.lnk) do if not defined OPENGUI_EXE set "OPENGUI_EXE=%%~fI"

if defined OPENGUI_EXE if exist "%OPENGUI_EXE%" (
    start "" "%OPENGUI_EXE%"
    echo [OK] OpenGUI shortcut: %OPENGUI_EXE%
    endlocal & exit /b 0
)

endlocal & exit /b 2
