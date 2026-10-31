@echo off
rem Chinese-named launcher for double-clicking; the real logic is ASCII-only
rem in start_yuanheng.bat so cmd's GBK code page cannot break it.
call "%~dp0start_yuanheng.bat" %*
exit /b %errorlevel%
