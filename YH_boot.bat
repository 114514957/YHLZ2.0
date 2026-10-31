@echo off

rem ------------------------------------------------------------------
rem YH single boot script (2026-10-20, ledger 0832).
rem
rem ONE implementation of the boot order:
rem   [1] service stack (ollama / gemma / daemon+workbench, no browser)
rem   [2] full watchdog (models + daemon only; QQ management=external)
rem   [3] QQ Bridge Lite (resume respects desired_state=stopped)
rem
rem Used by:
rem   - Windows Startup  -> YH 开机自启.lnk
rem   - Desktop shortcut -> YH 元亨利贞.lnk (via YH_workbench_normal.bat)
rem
rem Root uses the 8.3 short path: the real user folder name contains
rem non-ASCII em-dashes, which break plain-CMD batch files.
rem All text below is ASCII on purpose (Chinese in a GBK-parsed bat breaks).
rem Diagnostics: cache\logs\launcher.log (spawn decisions) + boot.log.
rem ------------------------------------------------------------------

set "YH_ROOT=C:\Users\ACE_WA~1\YHLZ\YH"
set "YH_PYW=%YH_ROOT%\.venv\Scripts\pythonw.exe"
set "YH_QQ_CFG=%YH_ROOT%\config\qq_bridge_lite.json"
set "YH_LOG=%YH_ROOT%\cache\logs\boot.log"

if not exist "%YH_PYW%" goto :nopython
if not exist "%YH_ROOT%\tools\yhlz_launcher.py" goto :nolauncher

rem net session succeeds only with an elevated token
net session >nul 2>&1
if not errorlevel 1 goto :elevated

if not exist "%YH_ROOT%\cache\logs" mkdir "%YH_ROOT%\cache\logs"
echo [%date% %time%] boot start>>"%YH_LOG%"

echo [1/3] service stack (models + daemon, no browser)...
start "yh-launch" "%YH_PYW%" -B "%YH_ROOT%\tools\yhlz_launcher.py" --no-browser

echo [2/3] full watchdog (models/daemon only; QQ management=external)...
start "yh-watchdog" "%YH_PYW%" -B "%YH_ROOT%\tools\yhlz_watchdog.py" --interval 60

echo [3/3] QQ Bridge Lite (single QQ owner; resume respects stopped state)...
start "yh-qq-lite" "%YH_PYW%" -B "%YH_ROOT%\tools\qq_bridge_control.py" resume --profile lite --config "%YH_QQ_CFG%"

echo.
echo   workbench : http://127.0.0.1:8321/
echo   logs      : %YH_ROOT%\cache\logs\  (launcher.log / boot.log / daemon.log)
echo   this window can be closed; services keep running.
ping -n 6 127.0.0.1 >nul 2>&1
exit /b 0

:elevated
echo [REFUSED] this window is ELEVATED (administrator token).
echo.
echo   Startup must run with NORMAL privileges. An admin token propagates
echo   to daemon / llama / ollama / NapCat and breaks the project rule.
echo   Double-click the desktop shortcut instead.
echo.
pause
exit /b 2

:nopython
echo [ERROR] venv pythonw not found: %YH_PYW%
pause
exit /b 3

:nolauncher
echo [ERROR] launcher not found: %YH_ROOT%\tools\yhlz_launcher.py
pause
exit /b 3
