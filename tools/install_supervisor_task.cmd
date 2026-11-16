@echo off
REM =========================================================
REM  Install YH self-sustain (Task Scheduler first, else Startup)
REM  ASCII ONLY on purpose: cmd.exe reads .cmd as GBK,
REM  so any Chinese text here becomes mojibake and breaks parsing.
REM =========================================================
setlocal
set "RUN=%~dp0run_supervisor.cmd"
if not exist "%RUN%" (
  echo [X] missing run_supervisor.cmd
  goto done
)

echo [1/2] try scheduled task "YH-Supervisor" ...
schtasks /create /f /tn "YH-Supervisor" /sc onlogon /rl limited /it /tr "%RUN%"
if not errorlevel 1 (
  schtasks /run /tn "YH-Supervisor"
  echo     task created and started
  goto verify
)
echo     task create failed, fallback to Startup folder

echo [2/2] copy into Startup folder ...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /y "%RUN%" "%STARTUP%\YH-supervisor.cmd" >nul
if errorlevel 1 (
  echo [X] copy failed: %STARTUP%
  goto done
)
echo     copied: %STARTUP%\YH-supervisor.cmd
start "" /min "%STARTUP%\YH-supervisor.cmd"

:verify
echo.
echo waiting 20s for daemon ...
timeout /t 20 >nul
netstat -ano | findstr ":8321" | findstr LISTENING
if errorlevel 1 (echo [X] 8321 not listening) else (echo [OK] daemon up)

:done
echo.
echo log: %~dp0..\cache\logs\supervisor.log
pause
