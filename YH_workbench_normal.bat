@echo off
rem Kept for compatibility: the desktop shortcut points here.
rem Real logic lives in start_yuanheng.bat (2026-10-22 rebuild):
rem start services -> wait for 8321 -> open workbench -> log.
rem   double-click                    start + wait + open
rem   YH_workbench_normal.bat check   prerequisites only, no spawn
call "%~dp0start_yuanheng.bat" %*
exit /b %errorlevel%
