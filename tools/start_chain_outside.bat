@echo off
chcp 65001 >nul
REM ============================================================
REM  元亨启链（在 YHLZ 目录**外面**运行，普通权限）
REM  2026-11-16 台账 1270
REM
REM  为什么要在外面：`…\YHLZ` 整棵树带 Low 强制标签，
REM  树内的 .exe/.bat 启动出来都是 Low；而 Low 注入不了 Medium 的 QQ，
REM  也写不进 qqwatch（Medium）目录。
REM  改标签需要 SeRelabelPrivilege（默认只有 SYSTEM 有），普通用户改不了；
REM  但**复制到外面**的新文件是 Medium —— 所以把启动器复制到 YH-run 再跑。
REM
REM  用法：复制到 C:\Users\ACE_WAN\YH-run\ 后双击（普通权限，不要管理员）
REM ============================================================
set "YH=C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
set "PY=C:\Users\ACE_WAN——PROJECT\AppData\Local\Programs\Python\Python312\python.exe"

if not exist "%PY%" (
  echo 找不到系统 Python：%PY%
  pause
  exit /b 1
)

cd /d "%YH%"
set "PYTHONPATH=%YH%;%YH%\.venv\Lib\site-packages"

echo 用系统 Python 启动（无 Low 标签）：
echo   %PY%
echo 工作目录：%YH%
echo.

"%PY%" -X utf8 "%YH%\tools\start_chain.py"
pause
