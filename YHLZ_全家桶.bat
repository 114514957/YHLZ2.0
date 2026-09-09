@echo off
chcp 65001 >nul
rem 全家桶: ensure services -> open workbench -> start desktop pet
start "yhlz-launch" "C:\Users\ACE_WA~1\YHLZ\.venv\Scripts\python.exe" -B "C:\Users\ACE_WA~1\YHLZ\tools\yhlz_launcher.py"
timeout /t 6 /nobreak >nul
start "yhlz-pet" "C:\Users\ACE_WA~1\YHLZ\desktop\node_modules\electron\dist\electron.exe" "C:\Users\ACE_WA~1\YHLZ\desktop"
