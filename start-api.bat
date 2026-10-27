@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "TOKENIZERS_PARALLELISM=false"

echo [Breeze TTS 2] 启动流式 API ...
echo [Breeze TTS 2] 地址: http://127.0.0.1:7860
echo [Breeze TTS 2] 接口: POST /v1/audio/speech  (返回 24kHz s16le 单声道 PCM)
echo.

".venv\Scripts\python.exe" -m breeze_infer.api "checkpoints\Breeze-TTS-2" --host 127.0.0.1 --port 7860 %*

if errorlevel 1 (
  echo.
  echo [错误] API 启动失败，请查看上方日志。
  pause
)
endlocal
