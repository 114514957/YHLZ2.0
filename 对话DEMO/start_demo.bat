@echo off
chcp 65001 >nul 2>&1
title YHLZ 2.0 Demo Launcher
cd /d "%~dp0"

:: UTF-8 环境 (避免中文/emoji 乱码)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==================================================
echo   YHLZ 2.0 Demo Launcher
echo   WebUI: http://127.0.0.1:5050
echo   Close this window or press Ctrl+C to exit
echo   (child processes will be cleaned up automatically)
echo ==================================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    echo Please install Python 3.10+ and add to PATH
    pause
    exit /b 1
)

:: Check Flask
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing Flask...
    python -m pip install flask flask-cors --quiet
)

:: Kill any existing demo processes on port 5050
echo [INFO] Checking for existing processes on port 5050...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5050" ^| findstr "LISTENING"') do (
    echo [INFO] Killing old process PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

:: Start Demo WebUI
echo [INFO] Starting YHLZ 2.0 Demo WebUI...
echo [INFO] Browser will open automatically at http://127.0.0.1:5050
echo.
python demo_webui.py

:: If Python exits unexpectedly
echo.
echo [INFO] Demo WebUI has stopped.
pause
