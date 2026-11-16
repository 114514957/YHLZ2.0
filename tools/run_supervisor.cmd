@echo off
REM Entry for supervisor. Absolute path on purpose:
REM this file is COPIED into the Startup folder, where %~dp0.. would point
REM to ...\Programs instead of the repo, so autostart did nothing.
cd /d "C:\Users\ACE_WAN??PROJECT\YHLZ\YH"
.venv\Scripts\python.exe -X utf8 tools\yh_supervisor.py %*
