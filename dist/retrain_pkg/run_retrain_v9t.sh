#!/bin/bash
# V9 重训（v9t / 1 epoch）—— 2026-10-25
#
# 与上次的唯一差别：数据换 v9t（5959 条）、epoch 3→1。
# 起因：上次 v9y 6765 条跑 3 epoch，eval_loss 在 step 400 触底 2.2432 后回升到 2.4116，
# 后 869 步白训。1 epoch 约 423 步，正落在最佳区间。
#
# 复用上次踩过的坑：Qwen3-4B 的 config.json 需要 patch 掉 sliding_window 才能被
# transformers 正常加载（fix_launch.sh 里的做法）。
#
# 用法（新实例上传解压后）：
#   bash run_retrain_v9t.sh
exec > /root/autodl-tmp/logs/retrain_v9t.log 2>&1
set -x
date

echo '=== 0. 环境 ==='
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
df -h /root/autodl-tmp | tail -1
mkdir -p /root/autodl-tmp/logs

PY=/root/miniconda3/bin/python
PIP=/root/miniconda3/bin/pip
BASE=/root/autodl-tmp/models/Qwen3-4B
WORK=/root/yh/retrain_pkg

echo '=== 1. 依赖（缺才装）==='
$PY -c "import transformers,peft,datasets,accelerate" 2>/dev/null || \
  $PIP install -q --upgrade 'transformers==5.20.2' 'peft==0.21.2' 'datasets==5.1.0' 'accelerate==1.15.0' \
       -i https://mirrors.aliyun.com/pypi/simple/
$PY -c "import bitsandbytes" 2>/dev/null || \
  $PIP install -q bitsandbytes==0.50.2 -i https://mirrors.aliyun.com/pypi/simple/
$PY -c "import modelscope" 2>/dev/null || \
  $PIP install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/
$PY -c "import transformers,peft,datasets,accelerate,torch;print('tf',transformers.__version__,'peft',peft.__version__,'torch',torch.__version__,torch.cuda.is_available())"

echo '=== 2. 下 Qwen3-4B（已有则跳过）==='
if [ ! -f "$BASE/config.json" ]; then
  /root/miniconda3/bin/modelscope download --model Qwen/Qwen3-4B --local_dir $BASE
fi
ls -la $BASE | head -12

echo '=== 3. patch sliding_window（上次踩的坑）==='
$PY - <<'EOF'
import json
p = '/root/autodl-tmp/models/Qwen3-4B/config.json'
cfg = json.load(open(p))
print('before: sliding_window=', cfg.get('sliding_window'), 'use_sliding_window=', cfg.get('use_sliding_window'))
if cfg.get('sliding_window') is None:
    cfg.pop('sliding_window', None)
json.dump(cfg, open(p, 'w'), indent=2, ensure_ascii=False)
print('patched')
from transformers import AutoConfig
c = AutoConfig.from_pretrained('/root/autodl-tmp/models/Qwen3-4B')
print('config OK, sliding_window =', getattr(c, 'sliding_window', '<absent>'))
EOF

echo '=== 4. 数据核对（必须是 v9t 5959）==='
$PY - <<'EOF'
import io, json
for sp in ('train', 'val'):
    p = '/root/yh/retrain_pkg/sft_persona_v9t_%s.jsonl' % sp
    rows = [json.loads(x) for x in io.open(p, encoding='utf-8') if x.strip()]
    print(sp, len(rows), '条')
    assert rows[0]['messages'][0]['role'] == 'system', '首条不是 system'
print('DATA_OK')
EOF

echo '=== 5. dry-run ==='
cd $WORK
$PY finetune_train.py --config config/finetune.qwen3-4b.v9t.1ep.json --base $BASE --dry-run
DRC=$?
echo DRYRUN_RC=$DRC
if [ $DRC -ne 0 ]; then
  echo 'DRY RUN FAILED - 停下，不启动训练'
  exit 1
fi

echo '=== 6. 启动训练（后台）==='
TOKENIZERS_PARALLELISM=false nohup $PY finetune_train.py \
  --config config/finetune.qwen3-4b.v9t.1ep.json \
  --base $BASE > /root/autodl-tmp/logs/train_v9t.log 2>&1 &
echo TRAIN_PID=$!

sleep 180
echo '=== 7. 三分钟后的状态 ==='
tail -c 3000 /root/autodl-tmp/logs/train_v9t.log | tr '\r' '\n' | grep -a . | tail -20
echo '--- GPU ---'
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader
echo '--- 进程 ---'
pgrep -f 'finetune_train.py' >/dev/null && echo ALIVE || echo DEAD
date
echo '=== DONE ==='
