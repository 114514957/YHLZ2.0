@echo off
REM Start the daemon in the user session (launched by keepalive/explorer).
REM python.exe (NOT pythonw): the daemon prints one line to stdout.
cd /d "C:\Users\ACE_WA~1\YHLZ\YH"
set YHLZ_PROMPT_SCENE=1
set YHLZ_MEMORY_RECALL=v2
start "YH-daemon" /min ".venv\Scripts\python.exe" -B -m backend.target_daemon --port 8321
