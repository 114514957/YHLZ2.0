#!/usr/bin/env bash
# 元亨 · DPO 收尾（仅 chat 子集；保护工具能力）
# 前置：已有 SFT adapter（默认 v6）在云数据盘
# 用法： SFT_ADAPTER=/root/autodl-tmp/models/lora/yuanheng-v6-sft bash run_dpo_only.sh
set -euo pipefail
cd "$(dirname "$0")"

TAG="${TAG:-v6}"
DISK="/root/autodl-tmp"; [ -d "$DISK" ] || DISK="."
BASE_DIR="${BASE_DIR:-$DISK/models/gemma4-qat/gemma-4-E4B-it-qat-unquantized}"
SFT_ADAPTER="${SFT_ADAPTER:-$DISK/models/lora/yuanheng-$TAG-sft}"
DPO_OUT="${DPO_OUT:-$DISK/models/lora/yuanheng-$TAG-dpo}"
SFT_DATA="${SFT_DATA:-../sft_persona_${TAG}_train.jsonl}"
N_PAIRS="${N_PAIRS:-400}"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
python -m pip install -q -U "transformers>=5.15.1" peft trl accelerate datasets safetensors

echo "== 1. 构造偏好对（dpo_build 自动跳过工具轨迹）=="
python dpo_build.py --base "$BASE_DIR" --data "$SFT_DATA" --n "$N_PAIRS" \
  --out "$DISK/dpo_pairs_$TAG.jsonl"

echo "== 2. DPO（v2 温和参数：beta=0.05, lr=1e-5）=="
python dpo_train.py --base "$BASE_DIR" --sft-adapter "$SFT_ADAPTER" \
  --pairs "$DISK/dpo_pairs_$TAG.jsonl" --out "$DPO_OUT" --no-4bit \
  --epochs 1 --lr 1e-5 --beta 0.05

echo "== 完成 =="
echo "DPO: $DPO_OUT"
echo "回传： tar czf yuanheng-$TAG-dpo.tar.gz -C $(dirname "$DPO_OUT") $(basename "$DPO_OUT")"
