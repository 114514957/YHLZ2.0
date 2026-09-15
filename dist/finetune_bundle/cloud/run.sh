#!/usr/bin/env bash
# 元亨训练一键脚本（A100 / AutoDL Linux）：依赖 -> 下模型 -> SFT -> DPO -> 导出 GGUF
# 用法:  bash run.sh            # 默认 QLoRA 4bit；失败自动退 bf16
#        bash run.sh --bf16     # 直接 bf16 LoRA
set -euo pipefail
cd "$(dirname "$0")"

HF_MODEL="${HF_MODEL:-google/gemma-4-E4B-it}"
# AutoDL：大文件放数据盘；本机无则用当前目录
DISK="/root/autodl-tmp"; [ -d "$DISK" ] || DISK="."
BASE_DIR="${BASE_DIR:-$DISK/models/gemma4-hf/gemma-4-e4b-it}"
SFT_OUT="${SFT_OUT:-$DISK/models/lora/yuanheng-sft}"
DPO_OUT="${DPO_OUT:-$DISK/models/lora/yuanheng-dpo}"
SFT_DATA="${SFT_DATA:-../sft_persona_v3_train.jsonl}"
VAL_DATA="${VAL_DATA:-../sft_persona_v3_val.jsonl}"
MODE="${1:-qlora}"

echo "== 0. 依赖 =="
pip install -q -U pip
# 若镜像自带 torch+cuda 可跳过下面这行；否则按 CUDA 版本装
python - <<'PY' 2>/dev/null || pip install torch --index-url https://download.pytorch.org/whl/cu121
import torch; assert torch.cuda.is_available()
PY
pip install -q "transformers>=5.15.1" peft datasets accelerate bitsandbytes trl safetensors sentencepiece hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1

echo "== 1. 下载基座 =="
python - "$HF_MODEL" "$BASE_DIR" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1], local_dir=sys.argv[2])
print("base ready:", sys.argv[2])
PY

echo "== 2. SFT（$MODE）=="
python sft_train.py --tag v3 --multimodal --train "$SFT_DATA" --val "$VAL_DATA" \
  --base "$BASE_DIR" --out "$SFT_OUT" $( [ "$MODE" = "bf16" ] && echo "--no-4bit" ) \
  | tee sft.log

echo "== 3. 构造 DPO 偏好对（用基座生成 rejected）+ DPO 训练 =="
python dpo_build.py --base "$BASE_DIR" --data "$SFT_DATA" --n 400 --out dpo_pairs.jsonl | tee dpo_build.log
python dpo_train.py --base "$BASE_DIR" --sft-adapter "$SFT_OUT" \
  --pairs dpo_pairs.jsonl --out "$DPO_OUT" | tee dpo.log

echo "== 4. 导出 GGUF LoRA（可选，需 llama.cpp/convert_lora_to_gguf.py）=="
if [ -f llama.cpp/convert_lora_to_gguf.py ]; then
  python llama.cpp/convert_lora_to_gguf.py "$DPO_OUT" --outtype q8_0 --outfile yuanheng-dpo-lora.gguf || true
fi

echo "== 完成 =="
echo "SFT adapter : $SFT_OUT"
echo "DPO adapter : $DPO_OUT"
