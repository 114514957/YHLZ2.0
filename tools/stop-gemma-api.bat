@echo off
chcp 65001 >nul
title stop gemma API :8082
rem Stop gemma API :8082 only (does not touch :8081 yuanheng prod)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($p) { $p | ForEach-Object { try { Stop-Process -Id $_ -Force; Write-Host ('stopped PID ' + $_) } catch { Write-Host ('failed PID ' + $_) } } } else { Write-Host 'gemma-api :8082 is not running' }"
pause
