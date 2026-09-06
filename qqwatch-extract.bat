@echo off
chcp 65001 >nul
cd /d "C:\Users\ACE_WAN——PROJECT\YHLZ"
".venv\Scripts\python.exe" -B "cache\qqwatch\batch_extract.py"
echo.
pause
