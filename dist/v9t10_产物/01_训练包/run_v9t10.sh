#!/bin/bash
# v9t10 一键训练
#   数据 = v9t8 的（齐全：含 identity_ai / internal_refusal / material_full / qq_short）
#   权重 = material_full 0.8→0.4（Σw 229.6→114.8，6.29%→3.24%，按台账 1113 的 5% 红线）
#   模型 = target_modules 加上 MLP（q/k/v/o + gate/up/down）
# 预计：772 步 / 39 分钟；adapter ≈139.6 MB
set -e
cd /root/yh/retrain_pkg_gemma_v9t10

PIP=/root/miniconda3/bin/pip
PY=/root/miniconda3/bin/python
BASE=/root/autodl-tmp/models/gemma-4-e4b-it
OUT=/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10
CFG=config/finetune.gemma4.v9t10lora.json

echo "== 环境 =="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
df -h /root/autodl-tmp | tail -1

echo "== 基座自检 =="
ls -l "$BASE/model.safetensors" || { echo "缺基座：$BASE"; exit 1; }

echo "== 数据 =="
echo "train $(( $(wc -l < sft_persona_v9t10_train.jsonl) )) 条（应 5931）"
echo "val   $(( $(wc -l < sft_persona_v9t10_val.jsonl) )) 条（应 978）"

echo "== 依赖 =="
$PIP install -q 'transformers==5.20.2' 'peft==0.21.2' 'datasets==5.1.0' \
  'accelerate==1.15.0' 'bitsandbytes==0.50.2'

echo "== 🔴 预检：文本塔 MLP 能不能挂 LoRA（不过就不训）=="
$PY preflight_mlp.py "$BASE" || { echo "❌ 预检失败：MLP 不是标准 Linear 或匹配数不对，停止。"; exit 3; }

echo "== dry-run =="
$PY finetune_train.py --config "$CFG" --base "$BASE" --dry-run 2>&1 | tail -12

echo "== 启动训练 =="
mkdir -p /root/autodl-tmp/logs
TOKENIZERS_PARALLELISM=false nohup $PY finetune_train.py \
  --config "$CFG" --base "$BASE" \
  > /root/autodl-tmp/logs/train_v9t10.log 2>&1 &
echo "TRAIN_PID=$!"
sleep 45
echo "== 头 45 秒日志 =="
grep -a "trainable params" /root/autodl-tmp/logs/train_v9t10.log || tail -5 /root/autodl-tmp/logs/train_v9t10.log
echo
echo "核对：trainable params 应 ≈34.9M（v9t6/7/8 都是 9.08M）。不是就立刻停。"
echo "跟进：tail -f /root/autodl-tmp/logs/train_v9t10.log"
