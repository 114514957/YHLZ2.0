@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "VPY=C:\Users\ACE_WA~1\YHLZ\.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo [ERROR] venv python not found
    pause
    exit /b 1
)
echo =============================================
echo   YHLZ Voice Dialog  (local end-to-end)
echo   - 1 speak a turn | 2 close | 0 exit
echo   RNNoise + SenseVoice + Gemma + Qwen3-TTS
echo =============================================
echo.
"%VPY%" -B "%~dp0tools\voice_dialog.py" %*
pause
