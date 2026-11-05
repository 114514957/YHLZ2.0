@echo off
rem background launcher for testing (log -> console.log)
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" "%~dp0server.py" > "%~dp0console.log" 2>&1 < nul
