@echo off
chcp 936 >nul
rem 双击本文件登录元亨号（3655185302）的 NapCat。
rem 直接双击 qqwatch\shell\launcher-user.bat 时，Explorer 可能不给 cwd，
rem %cd% 会变成 C:\Windows\System32，于是它去 System32 找
rem NapCatWinBootMain.exe，报 not recognized。这里先把 cwd 钉死再调用。
cd /d "%~dp0..\..\qqwatch\shell"
if not exist "NapCatWinBootMain.exe" (
  echo [ERROR] 找不到 NapCat shell，当前 cwd=%CD%
  pause
  exit /b 3
)
echo cwd=%CD%
echo launching NapCat (uin 3655185302) ...
call launcher-user.bat 3655185302
set "RC=%errorlevel%"
echo.
echo NapCat 已退出（退出码 %RC%）
pause
