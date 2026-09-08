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
echo   TTS-test / Voice-capture test entry
echo   - type 1 to listen one utterance
echo   - say a sentence, stop 3s to end
echo   - recognized text is printed
echo =============================================
echo.
"%VPY%" -B "%~dp0tools\tts_test_start.py" %*
pause
