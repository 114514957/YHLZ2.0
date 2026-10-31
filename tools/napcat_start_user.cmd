@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
rem ---------------------------------------------------------------------------
rem 2026-10-29 fix: the project now lives at ...\YHLZ\YH\tools, so "%~dp0..\.."
rem resolves to ...\YHLZ (not ...\PROJECT) and ...\YHLZ\qqwatch does not exist.
rem A missing /D directory makes `start` fail, which surfaced in the workbench as
rem "普通 CMD 启动请求失败，请检查本地启动环境".
rem Resolution order:
rem   1. YHLZ_NAPCAT_SHELL, which backend/napcat_launcher.py always passes in
rem   2. three levels up from tools\ (…\PROJECT\qqwatch)
rem ---------------------------------------------------------------------------
if defined YHLZ_NAPCAT_SHELL for %%I in ("%YHLZ_NAPCAT_SHELL%") do set "YHLZ_NAPCAT_CWD=%%~dpI"
if not defined YHLZ_NAPCAT_CWD set "YHLZ_NAPCAT_CWD=%~dp0..\..\..\qqwatch"
for %%I in ("%YHLZ_NAPCAT_CWD%") do set "YHLZ_NAPCAT_CWD=%%~fI"
if defined YHLZ_NAPCAT_CWD if "%YHLZ_NAPCAT_CWD:~-1%"=="\" set "YHLZ_NAPCAT_CWD=%YHLZ_NAPCAT_CWD:~0,-1%"
if not exist "%YHLZ_NAPCAT_CWD%" exit /b 3

set "YHLZ_NAPCAT_ENTRY=%~dp0napcat_single_login.cmd"
if not exist "%YHLZ_NAPCAT_ENTRY%" exit /b 1

if defined YHLZ_NAPCAT_PROBE (
  echo cwd=%YHLZ_NAPCAT_CWD%
  echo entry=%YHLZ_NAPCAT_ENTRY%
  echo shell=%YHLZ_NAPCAT_SHELL%
  exit /b 0
)

start "YHLZ QQ" /D "%YHLZ_NAPCAT_CWD%" "%ComSpec%" /d /s /k ""%YHLZ_NAPCAT_ENTRY%""
exit /b %errorlevel%
