@echo off
rem Compatibility wrapper: primary entrypoint is YH_workbench_normal.bat (2026-10-21).
call "%~dp0YH_workbench_normal.bat" %*
exit /b %errorlevel%
