@echo off
chcp 65001 >nul
title gemma-uncensored API :8082
rem ============================================================
rem  gemma-uncensored remote API (llama-server :8082)
rem  start: double-click | log: cache\logs\gemma-api.log
rem  auth : C:\Users\Public\yhlz-secrets\gemma_open_api_key.txt
rem  note : keep the key file on an ASCII-only path - this build
rem         cannot open non-ascii paths for --api-key-file
rem  note : shares GPU with yuanheng prod :8081 -> run one at a time
rem ============================================================
set ROOT=%~dp0..
set LS=%ROOT%\models\llama-cuda\llama-server.exe
set M=%ROOT%\..\models\gemma4\gemma4-e4b-aggr-q3km.gguf
set P=%ROOT%\..\models\gemma4\mmproj-gemma4-e4b.gguf
set K=C:\Users\Public\yhlz-secrets\gemma_open_api_key.txt
set LOGDIR=%ROOT%\cache\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%date% %time%] starting gemma-uncensored :8082 >> "%LOGDIR%\gemma-api.log"
"%LS%" -m "%M%" --mmproj "%P%" --jinja -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -c 8192 --parallel 1 -rea off --host 0.0.0.0 --port 8082 --temp 1.0 --top-p 0.95 --top-k 64 --api-key-file "%K%" --alias gemma-uncensored >> "%LOGDIR%\gemma-api.log" 2>&1
