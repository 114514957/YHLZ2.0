@echo off
REM Run the daemon IN THE FOREGROUND so the scheduled task stays "Running".
REM Why: when a task finishes, Task Scheduler kills the whole job (including any
REM child started with `start` / DETACHED). Keeping the task alive keeps the
REM daemon alive. ASCII short path only (UTF-8 codepage safety).
cd /d "C:\Users\ACE_WA~1\YHLZ\YH"
set YHLZ_PROMPT_SCENE=1
set YHLZ_MEMORY_RECALL=v2
".venv\Scripts\python.exe" -B -m backend.target_daemon --port 8321
