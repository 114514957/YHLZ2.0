@echo off
rem GPU acceptance (single process, direct calls)
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0_gpu_direct.py"
