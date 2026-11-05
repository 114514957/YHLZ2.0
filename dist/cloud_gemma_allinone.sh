#!/bin/bash
# gemma 上云一条龙：steering 验证 → LoRA 全量训练 → 56 题评测
#
# 用法：
#   bash cloud_gemma_allinone.sh steer     # 只跑 steering
#   bash cloud_gemma_allinone.sh train     # 只训 LoRA
#   bash cloud_gemma_allinone.sh eval      # 只评测（有 adapter 就挂上，没有就评基座）
#   bash cloud_gemma_allinone.sh all       # steer + train（eval 要等训练完单独跑）
#
# 前置（由本地上传）：
#   /root/yh/gemma_steer_test.py  unified_prompt.py  persona_bank.py
#   /root/yh/cloud_eval_gemma.py
#   /root/yh/data/tool_registry/snapshot_latest.json
#   /root/retrain_pkg_gemma_v9t5.tar.gz
#
# HF_TOKEN 由外部 export（仅在底模缺失时需要）
set -u
MODE=${1:-all}
PY=/root/miniconda3/bin/python
BASE=/root/autodl-tmp/models/gemma-4-e4b-it
LOG=/root/autodl-tmp/logs
PKG=/root/yh/retrain_pkg_gemma_v9t5
ADAPTER=/root/autodl-tmp/models/lora/yuanheng-v9-gemma
mkdir -p "$LOG" "$(dirname "$BASE")"

echo "############ 0 环境 ############"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null
echo "  MODE=$MODE"
df -h /root/autodl-tmp | tail -1

echo ""
echo "############ 1 依赖 ############"
$PY - <<'PYEOF'
import importlib
need = {"transformers": "5.20.2", "peft": "0.21.2", "datasets": "5.1.0",
        "accelerate": "1.15.0", "bitsandbytes": "0.50.2"}
bad = []
for m, want in need.items():
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", "?")
        ok = (v == want)
        print("  %-16s %-10s %s" % (m, v, "" if ok else "(want %s)" % want))
        if not ok:
            bad.append(m)
    except ImportError:
        print("  %-16s MISSING" % m)
        bad.append(m)
print("NEED:" + " ".join(sorted(set(bad))))
PYEOF
NEED=$($PY -c "
import importlib
need={'transformers':'5.20.2','peft':'0.21.2','datasets':'5.1.0','accelerate':'1.15.0','bitsandbytes':'0.50.2'}
bad=[]
for m,w in need.items():
    try:
        mod=importlib.import_module(m)
        if getattr(mod,'__version__','?')!=w: bad.append(m)
    except ImportError: bad.append(m)
print(' '.join(sorted(set(bad))))
")
if [ -n "$NEED" ]; then
  echo "  → 安装: $NEED"
  /root/miniconda3/bin/pip install -q \
    "transformers==5.20.2" "peft==0.21.2" "datasets==5.1.0" \
    "accelerate==1.15.0" "bitsandbytes==0.50.2" 2>&1 | tail -3
else
  echo "  全部就绪"
fi

echo ""
echo "############ 2 底模 ############"
if [ -f "$BASE/model.safetensors" ]; then
  echo "  ✅ 已存在 $(stat -c %s "$BASE/model.safetensors") 字节"
else
  if [ -z "${HF_TOKEN:-}" ]; then
    echo "  ✗ 底模缺失且没设 HF_TOKEN。请先 export HF_TOKEN=xxx"
    exit 3
  fi
  echo "  从 google/gemma-4-E4B-it 下载（约 15 GB）…"
  HF_HUB_ENABLE_XET=0 HF_TOKEN="$HF_TOKEN" $PY - <<PYEOF
from huggingface_hub import snapshot_download
p = snapshot_download(
    repo_id="google/gemma-4-E4B-it",
    allow_patterns=["*.safetensors", "*.json", "*.model", "tokenizer*", "*.txt"],
    local_dir="$BASE",
)
print("  downloaded:", p)
PYEOF
fi

echo ""
echo "############ 3 steering 验证 ############"
if [ "$MODE" = "steer" ] || [ "$MODE" = "all" ]; then
  cd /root/yh
  echo "--- L14，强度 0/4/8 ---"
  $PY -u gemma_steer_test.py --layer 14 --strengths 0,4,8 --max-new 80 \
    2>&1 | grep -av "Loading weights" | tail -60
  echo ""
  echo "--- L21/L28，强度 4 ---"
  $PY -u gemma_steer_test.py --layers 21,28 --strengths 4 --max-new 80 \
    2>&1 | grep -av "Loading weights" | tail -45
else
  echo "  跳过"
fi

echo ""
echo "############ 4 LoRA 全量训练 ############"
if [ "$MODE" = "train" ] || [ "$MODE" = "all" ]; then
  mkdir -p "$PKG"
  tar -xzf /root/retrain_pkg_gemma_v9t5.tar.gz -C "$PKG"
  echo "  数据："
  wc -l "$PKG"/*.jsonl
  cd "$PKG"
  echo "--- dry-run ---"
  $PY finetune_train.py --config config/finetune.gemma4.v9t5lora.json \
      --base "$BASE" --dry-run 2>&1 | tail -20
  echo "--- 启动训练 ---"
  TOKENIZERS_PARALLELISM=false nohup $PY finetune_train.py \
    --config config/finetune.gemma4.v9t5lora.json --base "$BASE" \
    > "$LOG/train_gemma_v9t5.log" 2>&1 &
  echo "  TRAIN_PID=$!"
  echo "  日志：$LOG/train_gemma_v9t5.log"
  sleep 45
  tail -c 900 "$LOG/train_gemma_v9t5.log" | tr '\r' '\n' | grep -a . | tail -8
else
  echo "  跳过"
fi

echo ""
echo "############ 5 评测 ############"
if [ "$MODE" = "eval" ]; then
  cd /root/yh
  if [ -d "$ADAPTER" ]; then
    echo "  挂 adapter: $ADAPTER"
    YH_MODEL="$BASE" YH_ADAPTER="$ADAPTER" YH_TAG=gemma_v9t5_lora \
      $PY -u cloud_eval_gemma.py 2>&1 | tail -14
  else
    echo "  没有 adapter，评基座（对照 v7b 的 41/56）"
    YH_MODEL="$BASE" YH_TAG=gemma_base \
      $PY -u cloud_eval_gemma.py 2>&1 | tail -14
  fi
else
  echo "  跳过（训练完单独跑: bash cloud_gemma_allinone.sh eval）"
fi

echo ""
echo "############ 完成 ############"
ls -la "$LOG"/*.log 2>/dev/null | tail -5
