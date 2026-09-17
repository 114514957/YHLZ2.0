# 元亨 · 本地服务（llama.cpp CUDA + mmproj + LoRA）
# 用法：
#   .\serve_yuanheng.ps1                       # 默认：QAT-Q4 + mmproj + LoRA
#   .\serve_yuanheng.ps1 -NoLora               # 先不挂 LoRA（验证基座）
#   .\serve_yuanheng.ps1 -Ctx 1024 -Port 8080
param(
  [string]$Root   = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$Server = "$PSScriptRoot\..\..\models\llama-cuda\llama-server.exe",
  [string]$Base   = "$PSScriptRoot\..\..\models\gemma4-gguf\gemma-4-E4B_q4_0-it.gguf",
  [string]$Mmproj = "$PSScriptRoot\..\..\models\gemma4-gguf\gemma-4-E4B-it-mmproj.gguf",
  [string]$Lora   = "$PSScriptRoot\..\..\models\gguf-lora\yuanheng-v5-lora.gguf",
  [int]$Ctx = 2048, [int]$Port = 8080, [int]$Ngl = 99,
  [switch]$NoLora, [switch]$NoMmproj
)

if (-not (Test-Path $Server)) { Write-Error "找不到 llama-server: $Server"; exit 1 }
if (-not (Test-Path $Base))   { Write-Error "找不到基座 GGUF: $Base";   exit 1 }

$args = @('-m', $Base, '-ngl', "$Ngl", '-c', "$Ctx",
          '-rea', 'off',                     # 关思考，保元亨人设
          '--host', '127.0.0.1', '--port', "$Port", '--jinja')
if (-not $NoMmproj) {
  if (Test-Path $Mmproj) { $args += @('--mmproj', $Mmproj, '--mmproj-offload') }
  else { Write-Warning "无 mmproj，跳过（不能用图像/音频）: $Mmproj" }
}
if (-not $NoLora) {
  if (Test-Path $Lora) { $args += @('--lora', $Lora) }
  else { Write-Warning "无 LoRA，跳过（人格来自 system prompt）: $Lora" }
}

Write-Host "启动: $Server`n  $($args -join ' ')" -ForegroundColor Cyan
& $Server @args
