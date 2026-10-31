#!/bin/bash
# gemma-4-e4b + v9t5 全量数据 LoRA 训练（云端 A800 / 任意 ≥16G 卡）
set -e
PY=/root/miniconda3/bin/python
PKG=/root/yh/retrain_pkg_gemma_v9t5
LOG=/root/autodl-tmp/logs
BASE=/root/autodl-tmp/models/gemma-4-e4b-it
mkdir -p "$LOG" "$(dirname "$BASE")"

echo "===== 0 环境 ====="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null
echo "  底模: $BASE"
echo "  训练包: $PKG"
df -h /root/autodl-tmp | tail -1

echo ""
echo "===== 1 依赖 ====="
$PY - <<'PYEOF'
import importlib, sys
need = {"transformers": "5.20.2", "peft": "0.21.2", "datasets": "5.1.0",
        "accelerate": "1.15.0", "bitsandbytes": "0.50.2", "huggingface_hub": None}
missing = []
for m, want in need.items():
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", "?")
        flag = "" if (want is None or v == want) else " (want %s)" % want
        print("  %-18s %s%s" % (m, v, flag))
    except ImportError:
        missing.append(m)
        print("  %-18s MISSING" % m)
if missing:
    print("  → 需要装: %s" % " ".join(missing))
    sys.exit(9)
PYEOF
if [ $? -eq 9 ]; then
  /root/miniconda3/bin/pip install -q \
    "transformers==5.20.2" "peft==0.21.2" "datasets==5.1.0" \
    "accelerate==1.15.0" "bitsandbytes==0.50.2" 2>&1 | tail -3
fi

echo ""
echo "===== 2 底模（缺失则从 HF 下）====="
if [ ! -f "$BASE/model.safetensors" ]; then
  echo "  底模不在，从 google/gemma-4-E4B-it 下载（约 15 GB）…"
  $PY - <<'PYEOF'
import os
from huggingface_hub import snapshot_download
os.environ.setdefault("HF_HUB_ENABLE_XET", "0")
p = snapshot_download(
    repo_id="google/gemma-4-E4B-it",
    allow_patterns=["*.safetensors", "*.json", "*.model", "tokenizer*", "*.txt"],
    local_dir="/root/autodl-tmp/models/gemma-4-e4b-it",
)
print("  downloaded:", p)
PYEOF
else
  echo "  底模已存在"
fi

echo ""
echo "===== 3 dry-run ====="
cd "$PKG"
$PY finetune_train.py --config config/finetune.gemma4.v9t5lora.json --base "$BASE" --dry-run

echo ""
echo "===== 4 启动训练 ====="
TOKENIZERS_PARALLELISM=false nohup $PY finetune_train.py \
  --config config/finetune.gemma4.v9t5lora.json --base "$BASE" \
  > "$LOG/train_gemma_v9t5.log" 2>&1 &
echo "TRAIN_PID=$!"
sleep 60
tail -c 1200 "$LOG/train_gemma_v9t5.log" | tr '\r' '\n' | grep -a . | tail -12
