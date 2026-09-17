#!/usr/bin/env bash
# 元亨 · QAT 重训一键脚本（A100/A800 80G，Linux）
# 目标：在 QAT 未量化基座上重训 SFT+DPO，产物与部署基座
#      `google/gemma-4-E4B-it-qat-q4_0-gguf` 同源（LoRA 可正确挂载）。
# 用法： bash run_qat.sh                 # 默认 bf16
#        SFT_EPOCHS=2 bash run_qat.sh    # 覆盖任一变量
set -euo pipefail
cd "$(dirname "$0")"

REPO="${REPO:-google/gemma-4-E4B-it-qat-q4_0-unquantized}"   # 可训练的 QAT 权重(14.8G)
DISK="/root/autodl-tmp"; [ -d "$DISK" ] || DISK="."
BASE_DIR="${BASE_DIR:-$DISK/models/gemma4-qat/gemma-4-E4B-it-qat-unquantized}"
SFT_OUT="${SFT_OUT:-$DISK/models/lora/yuanheng-qat-sft}"
DPO_OUT="${DPO_OUT:-$DISK/models/lora/yuanheng-qat-dpo}"
SFT_DATA="${SFT_DATA:-../sft_persona_v4_train.jsonl}"
VAL_DATA="${VAL_DATA:-../sft_persona_v4_val.jsonl}"
N_PAIRS="${N_PAIRS:-400}"

echo "== 0. env =="
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"     # HF 直连被墙，走镜像
[ -n "${HF_TOKEN:-}" ] || { echo "请先 export HF_TOKEN=..."; exit 1; }
python -m pip install -q -U "transformers>=5.15.1" peft trl accelerate datasets safetensors
python -c "from transformers import Gemma4ForConditionalGeneration;print('Gemma4 OK')"

echo "== 1. 下载 QAT 未量化基座 =="
python - "$REPO" "$BASE_DIR" <<'PY'
import sys
from huggingface_hub import snapshot_download
p = snapshot_download(sys.argv[1], local_dir=sys.argv[2])
print("base:", p)
PY

echo "== 2. SFT（bf16 LoRA，塔冻结）=="
python sft_train.py --tag v4 --multimodal --no-4bit \
  --base "$BASE_DIR" --train "$SFT_DATA" --val "$VAL_DATA" --out "$SFT_OUT" \
  --epochs "${SFT_EPOCHS:-3}" --seq "${SEQ:-2048}" --batch "${BATCH:-4}" \
  --grad-accum "${GA:-4}" --lr "${LR:-2e-4}" --r 16 --alpha 32

echo "== 3. DPO（v2 温和参数才是对的：beta=0.05, lr=1e-5）=="
python dpo_build.py --base "$BASE_DIR" --data "$SFT_DATA" --n "$N_PAIRS" \
  --out "$DISK/dpo_pairs.jsonl"
python dpo_train.py --base "$BASE_DIR" --sft-adapter "$SFT_OUT" \
  --pairs "$DISK/dpo_pairs.jsonl" --out "$DPO_OUT" --no-4bit \
  --epochs 1 --lr 1e-5 --beta 0.05

echo "== 4. 导出 LoRA → GGUF（部署用；需 llama.cpp 的 convert_lora_to_gguf.py）=="
if [ -f "$DISK/llama.cpp/convert_lora_to_gguf.py" ]; then
  python "$DISK/llama.cpp/convert_lora_to_gguf.py" "$DPO_OUT" \
    --outfile yuanheng-lora.gguf --outtype q8_0 || true
fi

echo "== 完成 =="
echo "SFT: $SFT_OUT"; echo "DPO: $DPO_OUT"
echo "回传：tar czf yuanheng-qat.tar.gz -C $(dirname "$DPO_OUT") $(basename "$SFT_OUT") $(basename "$DPO_OUT")"
