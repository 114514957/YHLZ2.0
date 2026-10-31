@echo off
rem Compatibility wrapper: primary entrypoint is YH_test_start.bat (2026-10-21).
call "%~dp0YH_test_start.bat" %*
exit /b %errorlevel%
