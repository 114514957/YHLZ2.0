@echo off
chcp 65001 >nul
title 元亨桌面虚拟形象

echo ============================================================
echo   元亨 YHLZ 2.0 - 桌面虚拟形象启动器
echo ============================================================
echo.

cd /d "%~dp0"

REM 检查Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Node.js
    echo 请先安装 Node.js 18+: https://nodejs.org/
    pause
    exit /b 1
)

REM 安装依赖
if not exist "node_modules" (
    echo [安装] 首次运行，正在安装依赖...
    call npm install
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

echo.
echo [启动] 正在启动桌面虚拟形象...
echo.

call npm start

pause