$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$root = "C:\Users\ACE_WAN——PROJECT\YHLZ"
$py = "$root\.venv\Scripts\python.exe"

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
        catch { Write-Host "[daemon]  启动失败，请查看 daemon 日志" -ForegroundColor Red }
    }
}

function Check-Watcher {
    $w = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'qqwatcher watch' })
    if ($w.Count -gt 0) {
        $wids = ($w.ProcessId -join ",")
        Write-Host "[watcher] 运行中 (QQ 捕获，pid=$wids)" -ForegroundColor Green
        if ($w.Count -gt 1) {
            $keep = ($w | Sort-Object CreationDate | Select-Object -First 1).ProcessId
            $w | Where-Object { $_.ProcessId -ne $keep } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Write-Host "[watcher] 多实例已清理" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[watcher] 未运行，启动..." -ForegroundColor Yellow
        Start-Process cmd.exe -ArgumentList "/c","`"$root\qqwatch-run.bat`""
        Start-Sleep -Seconds 5
        Write-Host "[watcher] 已拉起（可见窗口）" -ForegroundColor Green
    }
}

function Check-NapCat {
    $qq = @(Get-Process NapCatWinBootMain, QQ -ErrorAction SilentlyContinue)
    if ($qq.Count -gt 0) {
        Write-Host "[NapCat]  运行中 (QQ 2258374446)" -ForegroundColor Green
    } else {
        Write-Host "[NapCat]  未运行 -- 请双击 qqwatch\start-napcat.bat" -ForegroundColor Yellow
    }
}

function Check-Knowledge {
    try {
        $n = & $py -B "$root\tools\qq_knowledge_count.py"
        Write-Host ("[记忆库]  QQ knowledge 条目 = " + $n) -ForegroundColor Green
    } catch {}
}

function Show-All {
    Write-Host ""
    Write-Host "----- 服务状态 -----" -ForegroundColor Cyan
    Check-Daemon
    Check-Watcher
    Check-NapCat
    Check-Knowledge
    Write-Host ""
    Write-Host "知识汇编: docs\知识汇编\    |    日记: docs\元亨的日记.md    |    任务表: docs\元亨的任务表.md"
    Write-Host ""
}

function Show-Menu {
    Write-Host "==============================" -ForegroundColor Cyan
    Write-Host "   YHLZ 测试中心" -ForegroundColor Cyan
    Write-Host "==============================" -ForegroundColor Cyan
    Write-Host "  1) 检查并启动全部服务（缺啥起啥）" -ForegroundColor White
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
        "1" { Show-All; Write-Host "服务就绪。" }
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
