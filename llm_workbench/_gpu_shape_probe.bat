@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0_gpu_shape_probe.py"
