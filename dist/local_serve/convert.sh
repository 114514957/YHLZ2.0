#!/usr/bin/env bash
# 元亨 · GGUF 转换工具链（LoRA→GGUF / HF→GGUF / 量化）
# 依赖：llama.cpp 源码（本仓 models/llama-cuda/src/llama.cpp-b10991）+ .venv 里的 gguf 包
# 用法：
#   bash convert.sh lora   <peft_adapter_dir> <out.gguf>
#   bash convert.sh hf     <hf_model_dir>     <out.gguf> [outtype=f16]
#   bash convert.sh quant  <in.gguf> <out.gguf> [Q4_K_M]
set -euo pipefail
PY="${PY:-.venv/Scripts/python.exe}"          # Linux 下改成 python
SRC="${LLAMA_SRC:-models/llama-cuda/src/llama.cpp-b10991}"
QUANT="${LLAMA_QUANT:-models/llama-cuda/llama-quantize.exe}"
CMD="${1:?lora|hf|quant}"

case "$CMD" in
  lora)
    ADAPTER="${2:?adapter dir}"; OUT="${3:?out.gguf}"
    "$PY" "$SRC/convert_lora_to_gguf.py" "$ADAPTER" --outfile "$OUT" --outtype q8_0
    ;;
  hf)
    INDIR="${2:?hf dir}"; OUT="${3:?out.gguf}"; TYPE="${4:-f16}"
    "$PY" "$SRC/convert_hf_to_gguf.py" "$INDIR" --outfile "$OUT" --outtype "$TYPE"
    ;;
  quant)
    IN="${2:?in.gguf}"; OUT="${3:?out.gguf}"; Q="${4:-Q4_K_M}"
    "$QUANT" "$IN" "$OUT" "$Q"
    ;;
  *) echo "unknown: $CMD"; exit 1;;
esac
echo "[ok] $CMD -> ${OUT:-$3}"
