@echo off
REM Start the QQ bridge in the USER SESSION (launched via explorer by keepalive.py).
REM Same reason as start_daemon.cmd: avoid being killed with the scheduled task's job.
cd /d "C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
".venv\Scripts\python.exe" -X utf8 tools\qq_bridge_control.py start --profile lite --config config\qq_bridge_lite.json
