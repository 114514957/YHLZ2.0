$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$root = "C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
$py = "$root\.venv\Scripts\python.exe"
$lite = "$root\cache\qq_bridge\lite"

# 2026-10-20 / ledger 0831：本中心不再启动旧 QQ 采集链（qqwatcher / NapCat 旧入口）。
# QQ 只由 QQ Bridge Lite 独占；这里只读状态，必要时用官方 control 拉起桥（不动 NapCat）。

function Check-Daemon {
    $up = $false
    try { $h = Invoke-RestMethod "http://127.0.0.1:8321/health" -TimeoutSec 3; $up = $true } catch {}
    if ($up) {
        Write-Host ("[daemon]  运行中 (8321)  status=" + $h.status + "  sessions=" + $h.sessions) -ForegroundColor Green
    } else {
        Write-Host "[daemon]  未运行，正在启动..." -ForegroundColor Yellow
        Start-Process $py -ArgumentList "-B","-m","backend.target_daemon","--port","8321" -WorkingDirectory $root -WindowStyle Hidden
        Start-Sleep -Seconds 7
        try { $h2 = Invoke-RestMethod "http://127.0.0.1:8321/health" -TimeoutSec 5; Write-Host "[daemon]  已启动 (8321)" -ForegroundColor Green }
        catch { Write-Host "[daemon]  启动失败，请查看 cache/logs/daemon.log" -ForegroundColor Red }
    }
}

function Get-BridgeState {
    $f = Join-Path $lite "bridge_status.json"
    if (-not (Test-Path $f)) { return $null }
    try { return Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Check-QQBridge {
    $st = Get-BridgeState
    if ($null -eq $st) {
        Write-Host "[QQ桥]    无状态文件（Lite 未启动过）" -ForegroundColor Yellow
        return
    }
    $state = [string]$st.state
    $online = [bool]$st.account_online
    $pid = [string]$st.pid
    if ($state -eq "connected" -and $online) {
        Write-Host "[QQ桥]    Lite 在线 (pid=$pid, connected, account_online=true)" -ForegroundColor Green
    } elseif ($state -eq "connected") {
        Write-Host "[QQ桥]    WS 已连，账号未在线 (pid=$pid) —— 可能需扫码登录" -ForegroundColor Yellow
    } else {
        Write-Host "[QQ桥]    未连接 state=$state pid=$pid" -ForegroundColor Yellow
    }
    $desired = "unknown"
    $df = Join-Path $lite "desired_state.json"
    if (Test-Path $df) { try { $desired = [string](Get-Content $df -Raw -Encoding UTF8 | ConvertFrom-Json).desired } catch {} }
    Write-Host ("[QQ桥]    期望状态=" + $desired + "（stopped 时登录不会自动恢复）") -ForegroundColor DarkGray
}

function Start-QQBridgeIfNeeded {
    $st = Get-BridgeState
    if ($null -ne $st -and [string]$st.state -eq "connected") { return }
    Write-Host "[QQ桥]    未连接 → 用官方 control 拉起（--no-napcat，不动 QQ 登录）..." -ForegroundColor Yellow
    & $py -B "$root\tools\qq_bridge_control.py" start --profile lite --config "$root\config\qq_bridge_lite.json" --no-napcat | Out-Host
}

function Check-Knowledge {
    $counter = "$root\tools\qq_knowledge_count.py"
    if (-not (Test-Path $counter)) { return }
    try {
        $n = & $py -B $counter
        Write-Host ("[记忆库]  QQ knowledge 条目 = " + $n) -ForegroundColor Green
    } catch {}
}

function Show-All {
    Write-Host ""
    Write-Host "----- 服务状态 -----" -ForegroundColor Cyan
    Check-Daemon
    Check-QQBridge
    Check-Knowledge
    Write-Host ""
    Write-Host "知识汇编: docs\知识汇编\    |    日记: docs\元亨的日记.md    |    任务表: docs\元亨的任务表.md"
    Write-Host "QQ 排障:  cache\qq_bridge\lite\bridge.log  |  tools\qq_bridge_control.py status --profile lite"
    Write-Host ""
}

function Show-Menu {
    Write-Host "==============================" -ForegroundColor Cyan
    Write-Host "   YHLZ 测试中心" -ForegroundColor Cyan
    Write-Host "==============================" -ForegroundColor Cyan
    Write-Host "  1) 检查并启动服务（daemon + QQ 桥，不动 NapCat）" -ForegroundColor White
    Write-Host "  2) 与元亨对话（CLI 前台会话）" -ForegroundColor White
    Write-Host "  3) 只看服务状态" -ForegroundColor White
    Write-Host "  0) 退出" -ForegroundColor White
    Write-Host "------------------------------" -ForegroundColor Cyan
}

Show-All
while ($true) {
    Show-Menu
    $choice = Read-Host "请选择"
    switch ($choice.Trim()) {
        "1" { Check-Daemon; Start-QQBridgeIfNeeded; Show-All }
        "2" {
            Write-Host ""
            Write-Host "进入元亨对话（输入 /exit 退出会话，返回本菜单）..." -ForegroundColor Yellow
            & $py -B -m backend.target_entry
            Write-Host ""
            Write-Host "会话结束。" -ForegroundColor Yellow
        }
        "3" { Show-All }
        "0" { Write-Host "再见。"; break }
        default { Write-Host "无效选择：" $choice -ForegroundColor Red }
    }
}
