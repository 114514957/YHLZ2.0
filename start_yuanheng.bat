@echo off
rem ===================================================================
rem YH startup entry - rebuilt 2026-10-22 (startup entry lost)
rem
rem Why this file exists:
rem   The old chain (YH_boot.bat -> launcher -> watchdog) lost its
rem   supervisor: a daemon restart killed the watchdog's process tree, so
rem   nothing was left to bring services back. This entry starts the three
rem   pieces, WAITS for the workbench to actually answer, and keeps a log
rem   so a silent pythonw failure is no longer invisible.
rem
rem ASCII only (Chinese text in a GBK-parsed .bat breaks).
rem Log: cache\logs\startup.log
rem ===================================================================
setlocal
set "YH_ROOT=C:\Users\ACE_WA~1\YHLZ\YH"
set "PYW=%YH_ROOT%\.venv\Scripts\pythonw.exe"
set "PY=%YH_ROOT%\.venv\Scripts\python.exe"
set "LOG=%YH_ROOT%\cache\logs\startup.log"

if not exist "%YH_ROOT%" goto :noroot
if not exist "%PYW%" goto :nopyw
if not exist "%PY%" goto :nopy
if not exist "%YH_ROOT%\tools\yhlz_launcher.py" goto :nolauncher
if not exist "%YH_ROOT%\tools\yhlz_watchdog.py" goto :nowatchdog
if not exist "%YH_ROOT%\cache\logs" mkdir "%YH_ROOT%\cache\logs"

rem --- refuse elevation: an admin token propagates to llama/daemon ---
net session >nul 2>&1
if not errorlevel 1 goto :elevated

call :log "===== start ====="

rem --- diagnostic mode: check prerequisites only, never spawn ---
if /i "%~1"=="check" goto :checkonly

rem --- already up? then only open the page ---
call :probe
if "%UP%"=="1" (
  call :log "workbench already up; opening browser only"
  start "" "http://127.0.0.1:8321/"
  goto :done
)

rem --- 1/3 launcher (brings up llama + daemon) ---
call :log "spawn launcher"
start "yh-launch" "%PYW%" -B "%YH_ROOT%\tools\yhlz_launcher.py" --no-browser

rem --- 2/3 watchdog (keeps models/daemon alive; QQ is external) ---
call :log "spawn watchdog"
start "yh-watchdog" "%PYW%" -B "%YH_ROOT%\tools\yhlz_watchdog.py" --interval 60

rem --- 3/3 QQ bridge lite (resume respects desired_state) ---
if exist "%YH_ROOT%\tools\qq_bridge_control.py" (
  call :log "spawn qq bridge lite"
  start "yh-qq-lite" "%PYW%" -B "%YH_ROOT%\tools\qq_bridge_control.py" resume --profile lite --config "%YH_ROOT%\config\qq_bridge_lite.json"
) else (
  call :log "qq bridge control missing; skipped"
)

rem --- wait up to 180s for the workbench ---
echo waiting for the workbench on 8321 (up to 180s) ...
set /a N=0
:wait
call :probe
if "%UP%"=="1" goto :ready
set /a N+=1
if %N% GEQ 60 goto :timeout
ping -n 4 127.0.0.1 >nul 2>&1
goto :wait

:ready
call :log "workbench up after ~%N% ticks"
echo.
echo   workbench : http://127.0.0.1:8321/
echo   log       : %LOG%
start "" "http://127.0.0.1:8321/"
goto :done

:timeout
call :log "TIMEOUT: workbench not answering after 180s"
echo.
echo   [FAIL] the workbench did not answer on 8321.
echo   Check these files:
echo     %LOG%
echo     %YH_ROOT%\cache\logs\launcher.log
echo     %YH_ROOT%\cache\logs\daemon.log
echo     %YH_ROOT%\cache\logs\llama-server.log
echo.
echo   Tip: if llama-server.log is empty, the model failed to load
echo        (GPU busy / wrong path). Close other GPU work and retry.
pause
goto :done

:probe
set "UP=0"
"%PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(1.5); sys.exit(0 if s.connect_ex(('127.0.0.1',8321))==0 else 1)" >nul 2>&1
if not errorlevel 1 set "UP=1"
goto :eof

:log
echo [%date% %time%] %~1>>"%LOG%"
goto :eof

:elevated
echo [REFUSED] this window is ELEVATED.
echo   Startup must run with normal privileges.
pause
exit /b 2

:noroot
echo [ERROR] not found: %YH_ROOT%
pause
exit /b 3
:nopyw
echo [ERROR] not found: %PYW%
pause
exit /b 3
:nopy
echo [ERROR] not found: %PY%
pause
exit /b 3
:nolauncher
echo [ERROR] not found: %YH_ROOT%\tools\yhlz_launcher.py
pause
exit /b 3
:nowatchdog
echo [ERROR] not found: %YH_ROOT%\tools\yhlz_watchdog.py
pause
exit /b 3

:checkonly
echo.
echo   [check] root        : %YH_ROOT%
echo   [check] pythonw     : %PYW%
echo   [check] python      : %PY%
echo   [check] launcher    : %YH_ROOT%\tools\yhlz_launcher.py
echo   [check] watchdog    : %YH_ROOT%\tools\yhlz_watchdog.py
call :probe
if "%UP%"=="1" (echo   [check] workbench   : UP on 8321) else (echo   [check] workbench   : DOWN on 8321)
call :log "check mode ok"
exit /b 0

:done
call :log "===== end ====="
exit /b 0
