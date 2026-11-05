@echo off
rem wait for the server to bind, then open the UI in the default browser
timeout /t 3 >nul
start "" http://127.0.0.1:8090
