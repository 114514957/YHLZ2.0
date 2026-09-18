#!/usr/bin/env bash
# 元亨 · 一次租卡全流程：DPO 收尾 → v7 语音适配（链在 DPO 产物上）
# 前置：bundle 已上传（含 voice/）；v6 SFT adapter 在云盘
# 用法： SFT_ADAPTER=/root/autodl-tmp/models/lora/yuanheng-v6-sft bash run_all.sh
set -euo pipefail
cd "$(dirname "$0")"

TAG="${TAG:-v6}"
DISK="/root/autodl-tmp"; [ -d "$DISK" ] || DISK="."
BASE_DIR="${BASE_DIR:-$DISK/models/gemma4-qat/gemma-4-E4B-it-qat-unquantized}"

echo "======== 阶段 A：DPO 收尾（纯 chat 子集，保护工具）========"
TAG="$TAG" SFT_ADAPTER="${SFT_ADAPTER:-}" BASE_DIR="$BASE_DIR" bash run_dpo_only.sh

DPO_ADAPTER="$DISK/models/lora/yuanheng-$TAG-dpo"
echo "======== 阶段 B：v7 语音适配（在 $DPO_ADAPTER 上继续）========"
SFT_ADAPTER="$DPO_ADAPTER" TAG="v7" BASE_DIR="$BASE_DIR" bash run_voice.sh

echo "======== 全部完成 ========"
echo "DPO : $DPO_ADAPTER"
echo "v7  : $DISK/models/lora/yuanheng-v7-sft"
echo "回传："
echo "  tar czf yuanheng-$TAG-dpo.tar.gz -C $(dirname "$DPO_ADAPTER") $(basename "$DPO_ADAPTER")"
echo "  tar czf yuanheng-v7-sft.tar.gz  -C $DISK/models/lora yuanheng-v7-sft"
