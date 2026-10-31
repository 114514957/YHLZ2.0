@echo off
rem ------------------------------------------------------------------
rem start-gemma.bat - DEPRECATED manual entry (2026-10-20, ledger 0831).
rem
rem It used to start the OLD gemma4-e4b-aggr model on :8081 with the winget
rem llama-server (no LoRA, no --alias). The project then silently talked to a
rem non-Yuanheng model while /health stayed OK.
rem
rem It now forwards to the single production launcher (v6 QAT-Q4 base +
rem mmproj + v7b LoRA, --alias gemma-4-e4b). Do NOT add a second :8081
rem starter here.
rem ------------------------------------------------------------------

set "YHLZ_ROOT=C:\Users\ACE_WA~1\YHLZ\YH"
set "YHLZ_PYW=%YHLZ_ROOT%\.venv\Scripts\pythonw.exe"

if not exist "%YHLZ_PYW%" goto :nopython

echo [start-gemma] forwarding to tools\yhlz_launcher.py (production chain)
start "yhlz-launch" "%YHLZ_PYW%" -B "%YHLZ_ROOT%\tools\yhlz_launcher.py" --no-browser
exit /b 0

:nopython
echo [ERROR] venv pythonw not found: %YHLZ_PYW%
pause
exit /b 3
