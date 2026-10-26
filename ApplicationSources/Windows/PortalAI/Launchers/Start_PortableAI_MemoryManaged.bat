@echo off
setlocal EnableExtensions
title PortableAI - Memory Managed

REM ============================================================
REM PortableAI - balanced 24 GB VRAM profile - AV-clean startup
REM
REM Qwen stays useful for agent reasoning while leaving most VRAM
REM available for FLUX / Wan / ACE-Step.
REM
REM Tunables:
REM   QWEN_GPU_LAYERS=20  -> balanced default
REM   QWEN_IDLE_SLEEP=300 -> unload Qwen after 5 min idle
REM
REM v15.28 removes routine PowerShell use without changing the
REM Qwen memory profile or readiness/startup semantics.
REM ============================================================

set "QWEN_GPU_LAYERS=20"
set "QWEN_IDLE_SLEEP=300"

set "HERE=%~dp0"
set "ROOT="

if exist "%HERE%LLM\llamacpp\llama-server.exe" (
    set "ROOT=%HERE:~0,-1%"
)

if not defined ROOT if exist "%HERE%..\LLM\llamacpp\llama-server.exe" (
    for %%I in ("%HERE%..") do set "ROOT=%%~fI"
)

if not defined ROOT (
    echo ERROR: Could not locate PortableAI root.
    echo Expected LLM\llamacpp\llama-server.exe
    pause
    exit /b 1
)

cd /d "%ROOT%"

set "LLAMA=%ROOT%\LLM\llamacpp\llama-server.exe"
set "MODEL=%ROOT%\LLM\models\Qwen3.8-27B-Q4_K_M.gguf"
set "MMPROJ=%ROOT%\LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf"
set "HELPFILE=%TEMP%\portableai_llama_help_%RANDOM%.txt"

echo.
echo ============================================================
echo PortableAI - Memory Managed
echo Root: %ROOT%
echo Qwen GPU layers: %QWEN_GPU_LAYERS%
echo Qwen idle sleep: %QWEN_IDLE_SLEEP% seconds
echo Multimodal projector: CPU
echo ============================================================
echo.

if not exist "%LLAMA%" (
    echo ERROR: llama-server.exe not found:
    echo   "%LLAMA%"
    pause
    exit /b 1
)

if not exist "%MODEL%" (
    echo ERROR: Qwen model not found:
    echo   "%MODEL%"
    pause
    exit /b 1
)

if not exist "%MMPROJ%" (
    echo ERROR: mmproj not found:
    echo   "%MMPROJ%"
    pause
    exit /b 1
)

REM Verify that this llama.cpp build supports the memory-management flags.
"%LLAMA%" --help > "%HELPFILE%" 2>&1

findstr /C:"--sleep-idle-seconds" "%HELPFILE%" >nul
if errorlevel 1 (
    del "%HELPFILE%" >nul 2>&1
    echo ERROR: This llama.cpp build does not support --sleep-idle-seconds.
    echo Update the PortableAI llama.cpp binaries before using this launcher.
    pause
    exit /b 1
)

findstr /C:"--no-mmproj-offload" "%HELPFILE%" >nul
if errorlevel 1 (
    del "%HELPFILE%" >nul 2>&1
    echo ERROR: This llama.cpp build does not support --no-mmproj-offload.
    echo Update the PortableAI llama.cpp binaries before using this launcher.
    pause
    exit /b 1
)

del "%HELPFILE%" >nul 2>&1

REM If 8080 is already occupied, do not start a second Qwen.
call :Port8080Listening
if errorlevel 1 (
    echo [START] Starting memory-managed Qwen...
    REM Record the exact launch command for validated VRAM-handoff recovery.
    if not exist "%ROOT%\Agent\.runtime" mkdir "%ROOT%\Agent\.runtime" >nul 2>&1
    > "%ROOT%\Agent\.runtime\qwen_launch_command.txt" echo "%LLAMA%" -m "%MODEL%" --mmproj "%MMPROJ%" --no-mmproj-offload -ngl %QWEN_GPU_LAYERS% -c 16384 --sleep-idle-seconds %QWEN_IDLE_SLEEP% --host 127.0.0.1 --port 8080
    > "%ROOT%\Agent\.runtime\qwen_launch_executable.txt" echo %LLAMA%

    start "PortableAI - Qwen Balanced" /D "%ROOT%" "%LLAMA%" ^
      -m "%MODEL%" ^
      --mmproj "%MMPROJ%" ^
      --no-mmproj-offload ^
      -ngl %QWEN_GPU_LAYERS% ^
      -c 16384 ^
      --sleep-idle-seconds %QWEN_IDLE_SLEEP% ^
      --host 127.0.0.1 ^
      --port 8080

    echo [WAIT] Waiting for Qwen...
    call :WaitForQwen
    if errorlevel 1 (
        echo.
        echo ERROR: Qwen did not become ready within 5 minutes.
        echo Check the Qwen console for the actual error.
        pause
        exit /b 1
    )
    echo [OK] Qwen is ready.
) else (
    echo [OK] Port 8080 already has a Qwen/server process.
    echo NOTE: To apply this memory profile, close any old Qwen server first,
    echo       then run this launcher again.
)

echo [START] Looking for OpenGUI...
call :LaunchOpenGUI
if errorlevel 2 (
    echo.
    echo [WARN] Qwen is running but OpenGUI was not found automatically.
    echo Open OpenGUI manually.
    pause
    exit /b 2
)

echo.
echo ============================================================
echo PortableAI memory-managed profile is ready.
echo.
echo Qwen: partial GPU offload (%QWEN_GPU_LAYERS% layers)
echo mmproj: CPU
echo Idle sleep: %QWEN_IDLE_SLEEP% sec
echo ComfyUI/ACE-Step: started only when Qwen needs them
echo ============================================================
timeout /t 4 /nobreak >nul
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

if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs" for /r "%APPDATA%\Microsoft\Windows\Start Menu\Programs" %%I in (*OpenGUI*.lnk) do if not defined OPENGUI_EXE set "OPENGUI_EXE=%%~fI"
if not defined OPENGUI_EXE if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs" for /r "%ProgramData%\Microsoft\Windows\Start Menu\Programs" %%I in (*OpenGUI*.lnk) do if not defined OPENGUI_EXE set "OPENGUI_EXE=%%~fI"

if defined OPENGUI_EXE if exist "%OPENGUI_EXE%" (
    start "" "%OPENGUI_EXE%"
    echo [OK] OpenGUI shortcut: %OPENGUI_EXE%
    endlocal & exit /b 0
)

endlocal & exit /b 2
