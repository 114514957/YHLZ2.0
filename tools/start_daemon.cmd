@echo off
REM Start the daemon in the USER SESSION (launched via explorer by keepalive.py).
REM Why: a process started directly by a scheduled task belongs to that task's job
REM object and gets killed when the task instance ends. Going through explorer
REM breaks that lineage, so the daemon survives.
cd /d "C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
start "" ".venv\Scripts\pythonw.exe" -B -m backend.target_daemon --port 8321
