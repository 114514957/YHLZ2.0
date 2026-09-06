$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = "C:\Users\ACE_WAN——PROJECT\YHLZ"
$py = "$root\.venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== YHLZ 测试中心 ===" -ForegroundColor Cyan
Write-Host ""

# 1) daemon 8321
$up = $false
try { $h = Invoke-RestMethod "http://127.0.0.1:8321/health" -TimeoutSec 3; $up = $true } catch {}
if ($up) {
    Write-Host ("[daemon]  运行中  (8321)  status=" + $h.status + "  sessions=" + $h.sessions) -ForegroundColor Green
} else {
    Write-Host "[daemon]  未运行，正在启动..." -ForegroundColor Yellow
    Start-Process $py -ArgumentList "-B","-m","backend.target_daemon","--port","8321" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 6
    try { $h2 = Invoke-RestMethod "http://127.0.0.1:8321/health" -TimeoutSec 5; Write-Host "[daemon]  已启动 (8321)" -ForegroundColor Green }
    catch { Write-Host "[daemon]  启动失败！" -ForegroundColor Red }
}

# 2) watcher (QQ capture)
$w = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'qqwatcher watch' }
if ($w) {
    $wids = ($w.ProcessId -join ",');  Write-Host "[watcher] 运行中 (QQ 捕获，pid=$wids)" -ForegroundColor Green
} else {
    Write-Host "[watcher] 未运行，启动 qqwatch-run.bat..." -ForegroundColor Yellow
    Start-Process cmd.exe -ArgumentList "/c","`"$root\qqwatch-run.bat`""
    Start-Sleep -Seconds 4
    Write-Host "[watcher] 已拉起（可见窗口）" -ForegroundColor Green
}

# 3) NapCat / QQ
$qq = Get-Process NapCatWinBootMain, QQ -ErrorAction SilentlyContinue
if ($qq) {
    Write-Host "[NapCat]  运行中 (QQ 2258374446 登录)" -ForegroundColor Green
} else {
    Write-Host "[NapCat]  未运行 —— 请双击 qqwatch\start-napcat.bat 启动 QQ 捕获底座" -ForegroundColor Yellow
}

# 4) knowledge pipeline
try {
    $n = & $py -B "$root\tools\qq_knowledge_count.py"
    Write-Host ("[记忆库]  QQ knowledge 条目 = " + $n) -ForegroundColor Green
} catch {}

Write-Host ""
Write-Host "=== 测试入口 ===" -ForegroundColor Cyan
Write-Host "1) 与元亨对话(CLI):  .venv\Scripts\python.exe -m backend.target_entry" -ForegroundColor White
Write-Host "   可直接问：看下QQ链路有什么新知识 / 今天捕获怎么样 / 总结一下"
Write-Host "2) 元亨健康检查:    http://127.0.0.1:8321/health" -ForegroundColor White
Write-Host "3) 元亨日记:        docs\元亨的日记.md" -ForegroundColor White
Write-Host "4) 元亨任务表:      docs\元亨的任务表.md" -ForegroundColor White
Write-Host "5) QQ 知识汇编:     docs\知识汇编\" -ForegroundColor White
Write-Host "6) QQ 捕获日志:     qqwatch-run.bat 窗口 / cache\qqwatch\watcher.log" -ForegroundColor White
Write-Host ""
Write-Host "元亨工具面(自主可用): 记忆/日记/任务表/file/web + qq.status/process/digest/summarize"
Write-Host ""
