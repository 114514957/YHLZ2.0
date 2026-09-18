# 元亨 · 本地服务（llama.cpp CUDA + 多模态 + LoRA）
# 默认 = 项目生产配置：8081 / 别名 gemma-4-e4b / v6 LoRA / -c 8192（项目 prompt+29工具需 5k+ token）
# 用法：
#   powershell -File serve_yuanheng.ps1
#   powershell -File serve_yuanheng.ps1 -NoLora        # 只验基座
#   powershell -File serve_yuanheng.ps1 -Port 8080 -Alias yuanheng -Ctx 4096 -MmprojOnGpu
param(
  [string]$Server = "$PSScriptRoot\..\..\models\llama-cuda\llama-server.exe",
  [string]$Base   = "$PSScriptRoot\..\..\models\gemma4-gguf\gemma-4-E4B_q4_0-it.gguf",
  [string]$Mmproj = "$PSScriptRoot\..\..\models\gemma4-gguf\gemma-4-E4B-it-mmproj.gguf",
  [string]$Lora   = "$PSScriptRoot\..\..\models\gguf-lora\yuanheng-v6-lora.gguf",
  [int]$Ctx = 8192, [int]$Port = 8081, [int]$Ngl = 99, [int]$Parallel = 1,
  [string]$Alias = "gemma-4-e4b",
  [switch]$NoLora, [switch]$NoMmproj, [switch]$MmprojOnGpu
)

if (-not (Test-Path $Server)) { Write-Error "找不到 llama-server: $Server"; exit 1 }
if (-not (Test-Path $Base))   { Write-Error "找不到基座 GGUF: $Base";   exit 1 }

$srv = @('-m', $Base, '-ngl', "$Ngl", '-c', "$Ctx", '--parallel', "$Parallel",
         '-rea', 'off',                      # 关思考，保元亨人设
         '--alias', $Alias,                  # 项目按 gemma-4-e4b 找模型
         '--host', '127.0.0.1', '--port', "$Port", '--jinja')
if (-not $NoMmproj) {
  if (Test-Path $Mmproj) {
    $srv += @('--mmproj', $Mmproj)
    # 默认把 mmproj 放 CPU：8GB 显存下省 ~1.4GB，且只在输入时用
    if (-not $MmprojOnGpu) { $srv += '--no-mmproj-offload' }
  } else { Write-Warning "无 mmproj（不能用图/音）: $Mmproj" }
}
if (-not $NoLora) {
  if (Test-Path $Lora) { $srv += @('--lora', $Lora) }
  else { Write-Warning "无 LoRA（人格靠 system prompt）: $Lora" }
}

Write-Host "启动: $Server`n  $($srv -join ' ')" -ForegroundColor Cyan
& $Server @srv
