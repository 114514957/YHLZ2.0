@echo off
REM Wake NapCat (same as double-clicking launcher-user.bat).
REM ASCII short path only: this file may run under UTF-8 codepage,
REM where a Chinese path would be mojibake and 'cd' would fail.
cd /d "C:\Users\ACE_WA~1\qqwatch\shell"
call launcher-user.bat 3655185302
