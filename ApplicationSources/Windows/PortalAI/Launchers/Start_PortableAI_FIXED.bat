@echo off
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN
for %%# in ("%~dp0..") do set "_PAI_ROOT=%%~f#"
if exist "%_PAI_ROOT%\Runtime\BootstrapPython\python.exe" set "PATH=%_PAI_ROOT%\Runtime\BootstrapPython;%PATH%"
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_END
setlocal EnableExtensions
title PortableAI - OpenGUI + Qwen

REM ============================================================
REM PortableAI all-in-one launcher
REM Place this BAT in either:
REM   PortableAI\
REM or:
REM   PortableAI\Launchers\
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
REM Check whether Qwen is already listening.
REM ------------------------------------------------------------
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue; if($c){exit 0}else{exit 1}"

if errorlevel 1 (
    echo [START] Starting Qwen / llama.cpp...

    start "PortableAI - Qwen" /D "%ROOT%" "%LLAMA%" ^
      -m "%MODEL%" ^
      --mmproj "%MMPROJ%" ^
      -ngl 999 ^
      -c 16384 ^
      --host 127.0.0.1 ^
      --port 8080

    echo [WAIT] Waiting for Qwen to become ready...
    powershell -NoProfile -Command ^
      "$deadline=(Get-Date).AddMinutes(5); while((Get-Date)-lt $deadline){ try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/models' -TimeoutSec 3; if($r){ exit 0 } } catch {}; Start-Sleep -Seconds 2 }; exit 1"

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

REM ------------------------------------------------------------
REM Locate and launch OpenGUI.
REM ------------------------------------------------------------
echo [START] Looking for OpenGUI...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$candidates=@(" ^
  "  (Join-Path $env:LOCALAPPDATA 'Programs\OpenGUI\OpenGUI.exe')," ^
  "  (Join-Path $env:LOCALAPPDATA 'OpenGUI\OpenGUI.exe')," ^
  "  (Join-Path $env:ProgramFiles 'OpenGUI\OpenGUI.exe')" ^
  ");" ^
  "if(${env:ProgramFiles(x86)}){$candidates += (Join-Path ${env:ProgramFiles(x86)} 'OpenGUI\OpenGUI.exe')};" ^
  "$exe=$candidates | Where-Object {$_ -and (Test-Path $_)} | Select-Object -First 1;" ^
  "if(-not $exe){" ^
  " foreach($rp in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe','HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe')){" ^
  "  try{$v=(Get-ItemProperty $rp -ErrorAction Stop).'(default)'; if($v -and (Test-Path $v)){$exe=$v;break}}catch{}" ^
  " }" ^
  "};" ^
  "if(-not $exe){$cmd=Get-Command OpenGUI.exe -ErrorAction SilentlyContinue; if($cmd){$exe=$cmd.Source}};" ^
  "if($exe){Start-Process -FilePath $exe; Write-Host ('[OK] OpenGUI: '+$exe); exit 0};" ^
  "$menus=@((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),(Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'));" ^
  "$lnk=$menus | Where-Object {Test-Path $_} | ForEach-Object {Get-ChildItem $_ -Recurse -Filter '*OpenGUI*.lnk' -ErrorAction SilentlyContinue} | Select-Object -First 1;" ^
  "if($lnk){Start-Process -FilePath $lnk.FullName; Write-Host ('[OK] OpenGUI shortcut: '+$lnk.FullName); exit 0};" ^
  "exit 2"

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
echo Media:   http://127.0.0.1:%MEDIA_PORT%
echo OpenGUI: launched
echo ============================================================
timeout /t 3 /nobreak >nul
exit /b 0
