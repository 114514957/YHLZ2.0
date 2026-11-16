@echo off
REM Supervisor entry. pythonw = NO console window, so it cannot be
REM closed by accident (console version died at 22:02 when window closed).
REM This file is copied into the Startup folder, so the path is absolute.
cd /d "C:\Users\ACE_WAN¡ª¡ªPROJECT\YHLZ\YH"
".venv\Scripts\pythonw.exe" -X utf8 tools\yh_supervisor.py
