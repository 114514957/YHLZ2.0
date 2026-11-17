@echo off
REM Start daemon in the USER SESSION (launched via explorer by keepalive.py).
REM python.exe (NOT pythonw): daemon prints one line to stdout; pythonw has none.
cd /d "C:\Users\ACE_WAN¡ª¡ªPROJECT\YHLZ\YH"
REM 2026-11-17: scene trim only affects GROUP (public) prompts; private stays full.
set YHLZ_PROMPT_SCENE=1
set YHLZ_MEMORY_RECALL=v2
start "YH-daemon" /min ".venv\Scripts\python.exe" -B -m backend.target_daemon --port 8321
