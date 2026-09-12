@echo off
chcp 65001 >nul
title YHLZ 2.0

pushd "%~dp0"

echo ============================================================
echo   YHLZ 2.0
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

echo   [CHECK] Dependencies...
python -c "import flask" 2>nul
if %errorlevel% neq 0 (
    echo   [INSTALL] Flask...
    pip install flask flask-cors psutil requests -q
)
python -c "import PyQt5" 2>nul
if %errorlevel% neq 0 (
    echo   [INSTALL] PyQt5...
    pip install PyQt5 PyQtWebSockets -q
)

if not exist "logs" mkdir logs
if not exist "webui_templates" mkdir webui_templates
if not exist "webui_static" mkdir webui_static

if exist "ffmpeg\ffmpeg.exe" (
    set "PATH=%CD%\ffmpeg;%PATH%"
)

echo   [OK] Ready
echo.
echo   [START] WebUI...
echo   ---------------------------------------------------------
echo   URL: http://127.0.0.1:5000
echo.
echo   Services in WebUI:
echo     - Backend  (port 8000)
echo     - Avatar   (Live2D)
echo     - ASR      (Speech Recognition)
echo     - TTS      (Speech Synthesis)
echo   ---------------------------------------------------------
echo.

start "" http://127.0.0.1:5000
python webui_server.py

echo.
echo   [INFO] WebUI closed.
timeout /t 3 /nobreak >nul