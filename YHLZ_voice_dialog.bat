@echo off
rem Compatibility wrapper: primary entrypoint is YH_voice_dialog.bat (2026-10-21).
call "%~dp0YH_voice_dialog.bat" %*
exit /b %errorlevel%
