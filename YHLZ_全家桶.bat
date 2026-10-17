@echo off
chcp 65001 >nul
rem 全家桶: ensure services -> open workbench -> start desktop pet
rem ledger 0828: 从带 ELECTRON_RUN_AS_NODE=1 的环境启动时，Electron 会退化成
rem Node（require('electron') 只返回路径字符串 -> ipcMain undefined -> 桌宠秒崩，
rem 托盘图标也就不出现）。这里先清掉再拉桌宠。
start "yhlz-launch" "C:\Users\ACE_WA~1\YHLZ\.venv\Scripts\python.exe" -B "C:\Users\ACE_WA~1\YHLZ\tools\yhlz_launcher.py"
timeout /t 6 /nobreak >nul
set "ELECTRON_RUN_AS_NODE="
start "yhlz-pet" "C:\Users\ACE_WA~1\YHLZ\desktop\node_modules\electron\dist\electron.exe" "C:\Users\ACE_WA~1\YHLZ\desktop"
