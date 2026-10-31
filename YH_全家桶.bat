@echo off
chcp 65001 >nul
rem ------------------------------------------------------------------
rem 全家桶 = 兼容入口（2026-10-20，ledger 0830）。
rem
rem 以前这个 bat 自带一套启动逻辑（自己起 launcher、自己算 6 秒延时），
rem 和新入口 YH_workbench_normal.bat / YH_boot.bat 各拉一遍，就是
rem 「新旧都启动」的来源。现在只有一套实现：委托 YH_boot.bat 拉起
rem 服务栈 + 看门狗 + QQ Lite，然后开工作台、拉桌宠。
rem ------------------------------------------------------------------

call "%~dp0YH_boot.bat"
if errorlevel 1 exit /b %errorlevel%
start "" "http://127.0.0.1:8321/"

rem ledger 0828: 从带 ELECTRON_RUN_AS_NODE=1 的环境启动时，Electron 会退化成
rem Node（require('electron') 只返回路径字符串 -> ipcMain undefined -> 桌宠秒崩，
rem 托盘图标也就不出现）。这里先清掉再拉桌宠。
set "ELECTRON_RUN_AS_NODE="
start "yh-pet" "%~dp0desktop\node_modules\electron\dist\electron.exe" "%~dp0desktop"
exit /b 0
