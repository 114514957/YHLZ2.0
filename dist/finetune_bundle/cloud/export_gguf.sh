#!/usr/bin/env bash
# 导出 LoRA 为 GGUF（供 llama.cpp 服务挂载）——需联网克隆 llama.cpp
set -euo pipefail
cd "$(dirname "$0")"
ADAPTER="${1:-models/lora/yuanheng-dpo}"
OUT="${2:-yuanheng-dpo-lora.gguf}"
export HF_HUB_ENABLE_HF_TRANSFER=1

if [ ! -d llama.cpp ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp
fi
pip install -q -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt || true
python llama.cpp/convert_lora_to_gguf.py "$ADAPTER" --outtype q8_0 --outfile "$OUT"
echo "[ok] $OUT"
echo "服务挂载示例："
echo "  llama-server -m gemma4-e4b-aggr-q4km.gguf --mmproj mmproj-gemma4-e4b.gguf --lora $OUT"
