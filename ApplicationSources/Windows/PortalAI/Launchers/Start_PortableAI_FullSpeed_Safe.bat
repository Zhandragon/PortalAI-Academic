@echo off
setlocal EnableExtensions
title PortableAI - Qwen Full-Speed Safe Profile

REM ============================================================
REM PortableAI v15.39 - SAFE FULL-SPEED QWEN
REM
REM Performance change:
REM   -ngl 999             = offload all possible LLM layers to GPU
REM   --no-mmproj-offload  = keep vision projector on CPU for VRAM safety
REM   -c 16384             = preserve existing context capacity
REM
REM Deliberately omitted:
REM   --sleep-idle-seconds = no automatic Qwen cold-start after idle
REM
REM The existing PortableAI GPU handoff remains responsible for completely
REM releasing Qwen before Wan / FLUX / ACE-Step / MuseTalk needs the card.
REM ============================================================

set "HERE=%~dp0"
set "ROOT="

if exist "%HERE%..\LLM\llamacpp\llama-server.exe" (
    for %%I in ("%HERE%..") do set "ROOT=%%~fI"
)

if not defined ROOT if exist "%HERE%LLM\llamacpp\llama-server.exe" (
    set "ROOT=%HERE:~0,-1%"
)

if not defined ROOT (
    echo ERROR: Could not locate PortableAI root.
    echo Expected LLM\llamacpp\llama-server.exe
    exit /b 1
)

set "LLAMA=%ROOT%\LLM\llamacpp\llama-server.exe"
set "MODEL=%ROOT%\LLM\models\Qwen3.8-27B-Q4_K_M.gguf"
set "MMPROJ=%ROOT%\LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf"

for %%F in ("%LLAMA%" "%MODEL%" "%MMPROJ%") do (
    if not exist "%%~F" (
        echo ERROR: Required file missing:
        echo   %%~F
        exit /b 1
    )
)

powershell -NoProfile -Command ^
  "$c=Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue; if($c){exit 0}else{exit 1}"

if not errorlevel 1 (
    echo Qwen is already listening on port 8080.
    echo Stop the existing Qwen instance before changing profiles.
    exit /b 2
)

cd /d "%ROOT%"

start "PortableAI - Qwen Full-Speed Safe" /D "%ROOT%" "%LLAMA%" ^
  -m "%MODEL%" ^
  --mmproj "%MMPROJ%" ^
  --no-mmproj-offload ^
  -ngl 999 ^
  -c 16384 ^
  --host 127.0.0.1 ^
  --port 8080

exit /b 0
