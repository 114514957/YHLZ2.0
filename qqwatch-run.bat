@echo off
chcp 65001 >nul
echo [RETIRED] qqwatch 采集链已退役（2026-10-20 / ledger 0831）。
echo.
echo   QQ 归 QQ Bridge Lite 独占；旧 qqwatcher 是第二个 OneBot WS 消费者，
echo   会连 3001 与 Lite 桥抢消息，且配置还写着旧账号 2258374446。
echo   qq.export / qq.bootstrap 等工具在 external 模式下已 fail-closed。
echo.
echo   查看 QQ 状态：
echo     .venv\Scripts\python.exe -B tools\qq_bridge_control.py status --profile lite
exit /b 2
