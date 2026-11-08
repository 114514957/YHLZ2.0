# 重建桌面快捷方式（2026-11-07）
# 用法：在 YH 根目录执行
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\shortcuts\make_desktop_shortcuts.ps1
# 只创建/覆盖本脚本管理的三个入口，不动桌面其它快捷方式。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # YH
$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
$open = Join-Path $root 'tools\shortcuts\open_page.py'
$icon = Join-Path $root 'assets\icons\yh-app.ico'
$desk = [Environment]::GetFolderPath('Desktop')
$sh = New-Object -ComObject WScript.Shell

function New-Link {
    param($Name, $Url, $Port, $Boot, $Desc, $Icon)
    $path = Join-Path $desk $Name
    $lnk = $sh.CreateShortcut($path)
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "-B `"$open`" --url $Url --port $Port --boot $Boot"
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = $Desc
    $lnk.WindowStyle = 7   # 最小化，避免闪黑框
    $lnk.Save()
    Write-Host "已创建: $Name"
}

New-Link '元亨·翻唱工作站.lnk' 'http://127.0.0.1:8321/cover' 8321 'yh' `
    '元亨翻唱工作站（拖歌→分轨→换声→A/B→成品库）' $icon
New-Link '元亨·训练工作台.lnk' 'http://127.0.0.1:8321/train' 8321 'yh' `
    '元亨模型工作台（版本/对话/评测/记录 + 仪表盘；已并入 8321）' (Join-Path $root 'assets\icons\yhlz-app.ico')

# 元亨工作台：沿用原有「YH 元亨利贞.lnk」；若不存在则补一个
$main = Join-Path $desk 'YH 元亨利贞.lnk'
if (-not (Test-Path $main)) {
    $lnk = $sh.CreateShortcut($main)
    $lnk.TargetPath = Join-Path $root 'YH_workbench_normal.bat'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = 'YH 元亨工作台'
    $lnk.Save()
    Write-Host '已补建: YH 元亨利贞.lnk'
} else {
    Write-Host '保留原有: YH 元亨利贞.lnk'
}
