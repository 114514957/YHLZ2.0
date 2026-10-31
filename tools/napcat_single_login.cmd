@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "S=%YHLZ_NAPCAT_SHELL%"
if not exist "%S%\NapCatWinBootMain.exe" exit /b 1
if not exist "%YHLZ_QQ_EXE%" exit /b 2
set "ACCOUNT=%YHLZ_QUICK_UIN%"
set "NAPCAT_QUICK_ACCOUNT=%YHLZ_QUICK_UIN%"
set "NAPCAT_QUICK_PASSWORD="
set "NAPCAT_QUICK_PASSWORD_MD5="
set "NAPCAT_PATCH_PACKAGE=%S%\qqnt.json"
set "NAPCAT_LOAD_PATH=%S%\loadNapCat.js"
set "NAPCAT_INJECT_PATH=%S%\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=%S%\NapCatWinBootMain.exe"
set "NAPCAT_MAIN_PATH=%S%\napcat.mjs"
set "NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%"
rem NapCat 的相对路径（qqnt.json / config / cache）按 cwd 解析；cwd 不是 shell
rem 时它打完 argv[0] 就停（2026-10-29 工作台黑窗实测）。固定切到 shell 再启动。
cd /d "%S%"
"%NAPCAT_LAUNCHER_PATH%" "%YHLZ_QQ_EXE%" "%NAPCAT_INJECT_PATH%"
