#!/usr/bin/env bash
# 元亨 · v7 语音适配（在 v6 SFT adapter 上继续训练：ASR + 语音应答 + 文本 rehearsal）
# 前置：bundle 已上传（含 voice/）；v6 SFT adapter 在云盘
# 用法： SFT_ADAPTER=/root/autodl-tmp/models/lora/yuanheng-v6-sft bash run_voice.sh
set -euo pipefail
cd "$(dirname "$0")"

TAG="${TAG:-v7}"
DISK="/root/autodl-tmp"; [ -d "$DISK" ] || DISK="."
BASE_DIR="${BASE_DIR:-$DISK/models/gemma4-qat/gemma-4-E4B-it-qat-unquantized}"
SFT_ADAPTER="${SFT_ADAPTER:-$DISK/models/lora/yuanheng-v6-sft}"
OUT="${OUT:-$DISK/models/lora/yuanheng-$TAG-sft}"
REHEARSAL_N="${REHEARSAL_N:-120}"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
python -m pip install -q -U "transformers>=5.15.1" peft accelerate datasets safetensors soundfile

echo "== 0. 契约冒烟（3 样本 1 步：先证 input_features/mm_token_type_ids 前向可用）=="
python sft_voice.py --base "$BASE_DIR" --sft-adapter "$SFT_ADAPTER" \
  --train ../voice/voice_v1_train.jsonl --media-root .. \
  --out "$DISK/lora-smoke-$TAG" --no-4bit --smoke

echo "== 1. v7 语音 SFT（audio + rehearsal 混合，batch=1）=="
python sft_voice.py --base "$BASE_DIR" --sft-adapter "$SFT_ADAPTER" \
  --train ../voice/voice_v1_train.jsonl --val ../voice/voice_v1_val.jsonl \
  --rehearsal ../sft_persona_v6_train.jsonl --rehearsal-n "$REHEARSAL_N" \
  --media-root .. --out "$OUT" --no-4bit --epochs 2 --lr 1e-4

echo "== 完成 =="
echo "v7: $OUT"
echo "回传： tar czf yuanheng-$TAG-sft.tar.gz -C $(dirname "$OUT") $(basename "$OUT")"
