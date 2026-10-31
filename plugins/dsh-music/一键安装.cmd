@echo off
rem Double-click installer for dsh-music.
rem Everything is teed to plugins\dsh-music\_install.log so a failure stays readable
rem even if the window closes fast.
setlocal
cd /d "%~dp0"
set "LOG=%~dp0_install.log"
echo === dsh-music installer %date% %time% === > "%LOG%"

set "NODE="
for %%N in (node.exe) do if not defined NODE if exist "%%~$PATH:N" set "NODE=%%~$PATH:N"
if not defined NODE if exist "%LOCALAPPDATA%\Programs\nodejs\node.exe" set "NODE=%LOCALAPPDATA%\Programs\nodejs\node.exe"
if not defined NODE if exist "%ProgramFiles%\nodejs\node.exe" set "NODE=%ProgramFiles%\nodejs\node.exe"
if not defined NODE if exist "%ProgramFiles(x86)%\nodejs\node.exe" set "NODE=%ProgramFiles(x86)%\nodejs\node.exe"

if not defined NODE (
  echo [ERROR] node.exe not found.>> "%LOG%"
  echo [ERROR] node.exe not found - install Node 22+ or run install.mjs with DSH's bundled node.
  echo Log: %LOG%
  pause
  exit /b 1
)

echo node : %NODE%>> "%LOG%"
echo.>> "%LOG%"
"%NODE%" "%~dp0install.mjs" --profile desktop >> "%LOG%" 2>&1
set "RC=%errorlevel%"
echo.>> "%LOG%"
echo exit=%RC%>> "%LOG%"

type "%LOG%"
echo.
if "%RC%"=="0" (
  echo [OK] installed. Restart DSH or press F5, then ask: "列一下歌库"
) else (
  echo [FAILED] exit=%RC% - see the text above and %LOG%
)
pause
