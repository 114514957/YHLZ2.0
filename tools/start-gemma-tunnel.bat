@echo off
chcp 65001 >nul
title gemma tunnel :8082 -> cloudflare
rem ============================================================
rem  Cloudflare quick tunnel for gemma API :8082
rem  start: double-click; it prints https://xxxxx.trycloudflare.com
rem  put that URL + API key into your phone app (OpenAI settings)
rem  keep this window open; closing it kills the tunnel only
rem ============================================================
set CF=C:\Program Files (x86)\cloudflared\cloudflared.exe
"%CF%" tunnel --url http://127.0.0.1:8082 --no-autoupdate
pause
