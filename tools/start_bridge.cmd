@echo off
REM Start the QQ bridge in the user session.
cd /d "C:\Users\ACE_WA~1\YHLZ\YH"
".venv\Scripts\python.exe" -X utf8 tools\qq_bridge_control.py start --profile lite --config config\qq_bridge_lite.json
