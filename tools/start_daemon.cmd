@echo off
REM Start the daemon in the USER SESSION (launched via explorer by keepalive.py).
REM NOTE: must use python.exe, NOT pythonw.exe -- the daemon prints one startup
REM line to stdout, and pythonw has sys.stdout = None, which crashes it instantly.
cd /d "C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
start "YH-daemon" /min ".venv\Scripts\python.exe" -B -m backend.target_daemon --port 8321
