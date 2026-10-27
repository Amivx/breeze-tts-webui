@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "TOKENIZERS_PARALLELISM=false"

echo [Breeze TTS 2] 启动本地控制台（WebUI + API）...
echo [Breeze TTS 2] 请在浏览器打开:  http://127.0.0.1:7860/
echo.

start "" "http://127.0.0.1:7860/"

".venv\Scripts\python.exe" -m webui.server "checkpoints\Breeze-TTS-2" --host 127.0.0.1 --port 7860 %*

if errorlevel 1 (
  echo.
  echo [错误] 启动失败，请查看上方日志。
  pause
)
endlocal
