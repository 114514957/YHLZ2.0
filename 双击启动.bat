@echo off
chcp 65001 > nul
title YHLZ 2.0 - 智能语音助手

cd /d "%~dp0"

echo ================================================
echo           YHLZ 2.0 智能语音助手
echo ================================================
echo.
echo 正在启动...
echo.

.\venv\Scripts\python.exe chat_simple.py

if errorlevel 1 (
    echo.
    echo 程序已退出
    pause
)