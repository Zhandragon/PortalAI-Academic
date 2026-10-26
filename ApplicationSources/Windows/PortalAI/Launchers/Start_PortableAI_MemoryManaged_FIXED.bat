@echo off
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN
for %%# in ("%~dp0..") do set "_PAI_ROOT=%%~f#"
if exist "%_PAI_ROOT%\Runtime\BootstrapPython\python.exe" set "PATH=%_PAI_ROOT%\Runtime\BootstrapPython;%PATH%"
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_END
setlocal EnableExtensions
title PortableAI - Memory Managed

REM ============================================================
REM PortableAI - balanced 24 GB VRAM profile
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

"%LLAMA%" --help > "%HELPFILE%" 2>&1

findstr /C:"--sleep-idle-seconds" "%HELPFILE%" >nul
if errorlevel 1 (
    del "%HELPFILE%" >nul 2>&1
    echo ERROR: This llama.cpp build does not support --sleep-idle-seconds.
    pause
    exit /b 1
)

findstr /C:"--no-mmproj-offload" "%HELPFILE%" >nul
if errorlevel 1 (
    del "%HELPFILE%" >nul 2>&1
    echo ERROR: This llama.cpp build does not support --no-mmproj-offload.
    pause
    exit /b 1
)

del "%HELPFILE%" >nul 2>&1

powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue; if($c){exit 0}else{exit 1}"

if errorlevel 1 (
    echo [START] Starting memory-managed Qwen...
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
    powershell -NoProfile -Command ^
      "$deadline=(Get-Date).AddMinutes(5); while((Get-Date)-lt $deadline){ try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/models' -TimeoutSec 3; if($r){exit 0} } catch {}; Start-Sleep -Seconds 2 }; exit 1"

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
)

REM ------------------------------------------------------------
REM Start the local media preview server if it is not already up.
REM This is what makes generated media reachable from OpenGUI Markdown.
REM ------------------------------------------------------------
set "MEDIA_PORT=8765"
set "MEDIA_SERVER=%ROOT%\Agent\media_server.py"
set "MEDIA_LOG=%ROOT%\Agent\.runtime\media_server.log"
set "MEDIA_PYTHON="

if not exist "%ROOT%\Agent\.runtime" mkdir "%ROOT%\Agent\.runtime" >nul 2>&1

powershell -NoProfile -Command ^
  "try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%MEDIA_PORT%/health' -TimeoutSec 2;if($r.StatusCode -eq 200){exit 0}}catch{};exit 1"

if errorlevel 1 (
    if not exist "%MEDIA_SERVER%" (
        echo [WARN] Media preview server script not found:
        echo   "%MEDIA_SERVER%"
    ) else (
        for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined MEDIA_PYTHON set "MEDIA_PYTHON=%%P"

        if defined MEDIA_PYTHON (
            echo [START] Starting local media preview server on port %MEDIA_PORT%...
            start "PortableAI - Media Preview" /min /D "%ROOT%" "%MEDIA_PYTHON%" -u "%MEDIA_SERVER%" --root "%ROOT%" --host 127.0.0.1 --port %MEDIA_PORT% ^> "%MEDIA_LOG%" 2^>^&1
        ) else (
            where py.exe >nul 2>&1
            if not errorlevel 1 (
                echo [START] Starting local media preview server on port %MEDIA_PORT% using py -3...
                start "PortableAI - Media Preview" /min /D "%ROOT%" cmd /c "py -3 -u ""%MEDIA_SERVER%"" --root ""%ROOT%"" --host 127.0.0.1 --port %MEDIA_PORT% > ""%MEDIA_LOG%"" 2>&1"
            ) else (
                echo [WARN] Python 3 was not found on PATH. Media previews will not work.
            )
        )

        echo [WAIT] Waiting for media preview server...
        powershell -NoProfile -Command ^
          "$deadline=(Get-Date).AddSeconds(20);while((Get-Date)-lt $deadline){try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%MEDIA_PORT%/health' -TimeoutSec 2;if($r.StatusCode -eq 200){exit 0}}catch{};Start-Sleep -Milliseconds 500};exit 1"

        if errorlevel 1 (
            echo [WARN] Media preview server did not become ready.
            echo        See: "%MEDIA_LOG%"
        ) else (
            echo [OK] Media preview server: http://127.0.0.1:%MEDIA_PORT%
        )
    )
) else (
    echo [OK] Media preview server already running on port %MEDIA_PORT%.
)

echo [START] Looking for OpenGUI...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$candidates=@(" ^
  " (Join-Path $env:LOCALAPPDATA 'Programs\OpenGUI\OpenGUI.exe')," ^
  " (Join-Path $env:LOCALAPPDATA 'OpenGUI\OpenGUI.exe')," ^
  " (Join-Path $env:ProgramFiles 'OpenGUI\OpenGUI.exe')" ^
  ");" ^
  "if(${env:ProgramFiles(x86)}){$candidates+=(Join-Path ${env:ProgramFiles(x86)} 'OpenGUI\OpenGUI.exe')};" ^
  "$exe=$candidates|Where-Object {$_ -and (Test-Path $_)}|Select-Object -First 1;" ^
  "if(-not $exe){foreach($rp in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe','HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe')){try{$v=(Get-ItemProperty $rp -ErrorAction Stop).'(default)';if($v -and (Test-Path $v)){$exe=$v;break}}catch{}}};" ^
  "if(-not $exe){$cmd=Get-Command OpenGUI.exe -ErrorAction SilentlyContinue;if($cmd){$exe=$cmd.Source}};" ^
  "if($exe){Start-Process -FilePath $exe;Write-Host ('[OK] OpenGUI: '+$exe);exit 0};" ^
  "$menus=@((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),(Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'));" ^
  "$lnk=$menus|Where-Object {Test-Path $_}|ForEach-Object {Get-ChildItem $_ -Recurse -Filter '*OpenGUI*.lnk' -ErrorAction SilentlyContinue}|Select-Object -First 1;" ^
  "if($lnk){Start-Process -FilePath $lnk.FullName;Write-Host ('[OK] OpenGUI shortcut: '+$lnk.FullName);exit 0};exit 2"

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
echo Qwen: partial GPU offload (%QWEN_GPU_LAYERS% layers)
echo mmproj: CPU
echo Idle sleep: %QWEN_IDLE_SLEEP% sec
echo Media: http://127.0.0.1:%MEDIA_PORT%
echo ComfyUI/ACE-Step: started only when Qwen needs them
echo ============================================================
timeout /t 4 /nobreak >nul
exit /b 0
