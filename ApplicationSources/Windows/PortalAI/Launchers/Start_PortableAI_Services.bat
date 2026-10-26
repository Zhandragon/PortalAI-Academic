@echo off
setlocal
title PortableAI Services
cd /d "%~dp0.."

echo Starting llama.cpp Qwen server...
start "Qwen llama-server" cmd /k ""%CD%\LLM\llama.cpp\llama-server.exe" -m "%CD%\LLM\models\Qwen3.8-27B-Q4_K_M.gguf" --mmproj "%CD%\LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf" -ngl 999 -c 16384 --host 127.0.0.1 --port 8080"

timeout /t 2 /nobreak >nul

echo Starting ComfyUI...
start "ComfyUI" cmd /k "cd /d "%CD%\Generative\ComfyUI_windows_portable" && call run_nvidia_gpu.bat"

timeout /t 2 /nobreak >nul

echo Starting ACE-Step API...
start "ACE-Step API" cmd /k "cd /d "%CD%\Music\ACE-Step-1.5" && call start_api_server.bat"

echo.
echo Services requested:
echo   Qwen:     http://127.0.0.1:8080
echo   ComfyUI:  http://127.0.0.1:8188
echo   ACE-Step: http://127.0.0.1:8001
echo.
echo OpenGUI is not started here because its executable/install path can vary.
echo Once OpenGUI is open, point its OpenAI-compatible model endpoint at:
echo   http://127.0.0.1:8080/v1
echo.
pause
