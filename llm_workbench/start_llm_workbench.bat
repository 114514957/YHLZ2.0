@echo off
chcp 65001 >nul
title LLM Workbench :8090
rem Workbench UI  : 8090
rem llama-server  : 8091 (default, own instance only)
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo venv not found: %PY%
  pause
  exit /b 1
)
start "" "%~dp0_open_ui.bat"
"%PY%" "%~dp0server.py"
echo.
echo [workbench exited]
pause
