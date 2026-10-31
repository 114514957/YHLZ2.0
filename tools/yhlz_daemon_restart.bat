@echo off
rem Renamed 2026-10-21 (ledger 0951): path-independent restart helper.
rem The old hard-coded path contained non-ASCII em-dashes and broke in plain CMD.
cd /d "%~dp0.."
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8321 " ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 2 /nobreak >nul
start "YHdaemon" /min "%~dp0..\.venv\Scripts\python.exe" -B -m backend.target_daemon --port 8321
