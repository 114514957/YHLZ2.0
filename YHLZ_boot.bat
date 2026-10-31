@echo off
rem Compatibility wrapper: primary entrypoint is YH_boot.bat (2026-10-21).
call "%~dp0YH_boot.bat" %*
exit /b %errorlevel%
