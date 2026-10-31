#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包 v9t4t 重训上传包（含加固样本 + 剥标签修复）。

与 v9t 的差别：
  · 数据多了 159 条加固样本（寒暄 100 / 利贞身份 20 / 短自我 20 / 隐含工具 19）
  · 剥掉了 assistant 台词开头的「元亨：」标签（9 条）
  · train 6081 / val 960
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PKG = os.path.join(ROOT, "dist", "retrain_pkg_v9t4")
SRC_CFG = os.path.join(ROOT, "dist", "retrain_pkg", "config",
                       "finetune.qwen3-4b.v9t.1ep.json")
TRAIN = os.path.join(ROOT, "data", "finetune", "sft_persona_v9t4t_train.jsonl")
VAL = os.path.join(ROOT, "data", "finetune", "sft_persona_v9t4t_val.jsonl")
TRAINER = os.path.join(ROOT, "tools", "finetune_train.py")

RUN_SH = '''#!/bin/bash
# v9t4t 一键重训（加固样本 + 剥标签修复）
set -e
cd /root/yh/retrain_pkg_v9t4

PIP=/root/miniconda3/bin/pip
PY=/root/miniconda3/bin/python
BASE=/root/autodl-tmp/models/Qwen3-4B
OUT=/root/autodl-tmp/models/full/qwen3-4b-yuanheng-v9t4

echo "== 环境 =="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
df -h /root/autodl-tmp | tail -1

echo "== 装依赖 =="
$PIP install -q 'transformers==5.20.2' 'peft==0.21.2' 'datasets==5.1.0' \\
  'accelerate==1.15.0' 'bitsandbytes==0.50.2'

echo "== 数据 =="
echo "train $(( $(wc -l < sft_persona_v9t4t_train.jsonl) )) 条"
echo "val   $(( $(wc -l < sft_persona_v9t4t_val.jsonl) )) 条"

echo "== patch sliding_window =="
$PY - <<'PY'
import json, pathlib
p = pathlib.Path("/root/autodl-tmp/models/Qwen3-4B/config.json")
c = json.loads(p.read_text())
c.pop("sliding_window", None)
p.write_text(json.dumps(c, indent=2, ensure_ascii=False))
print("sliding_window ->", c.get("sliding_window"))
PY

echo "== dry-run 自检 =="
$PY finetune_train.py --config config/finetune.qwen3-4b.v9t4t.1ep.json \\
  --base "$BASE" --dry-run 2>&1 | head -20

echo "== 启动训练 =="
TOKENIZERS_PARALLELISM=false nohup $PY finetune_train.py \\
  --config config/finetune.qwen3-4b.v9t4t.1ep.json --base "$BASE" \\
  > /root/autodl-tmp/logs/train_v9t4.log 2>&1 &
echo "TRAIN_PID=$!"
sleep 30
tail -5 /root/autodl-tmp/logs/train_v9t4.log
echo "日志：/root/autodl-tmp/logs/train_v9t4.log"
'''


def main() -> int:
    if os.path.isdir(PKG):
        shutil.rmtree(PKG)
    os.makedirs(os.path.join(PKG, "config"))

    # 1. 训练脚本
    shutil.copy2(TRAINER, os.path.join(PKG, "finetune_train.py"))

    # 2. 数据
    for src, name in ((TRAIN, "sft_persona_v9t4t_train.jsonl"),
                      (VAL, "sft_persona_v9t4t_val.jsonl")):
        shutil.copy2(src, os.path.join(PKG, name))

    # 3. 配置（从 v9t 复制并改编）
    cfg = json.load(io.open(SRC_CFG, encoding="utf-8"))
    cfg["train_file"] = "/root/yh/retrain_pkg_v9t4/sft_persona_v9t4t_train.jsonl"
    cfg["val_file"] = "/root/yh/retrain_pkg_v9t4/sft_persona_v9t4t_val.jsonl"
    cfg["output_dir"] = "/root/autodl-tmp/models/full/qwen3-4b-yuanheng-v9t4"
    cfg["epochs"] = 1
    with io.open(os.path.join(PKG, "config",
                              "finetune.qwen3-4b.v9t4t.1ep.json"),
                 "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    # 4. 启动脚本
    with io.open(os.path.join(PKG, "run_retrain_v9t4t.sh"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(RUN_SH)

    # 5. 汇总
    n_train = sum(1 for _ in io.open(TRAIN, encoding="utf-8"))
    n_val = sum(1 for _ in io.open(VAL, encoding="utf-8"))
    tot = 0
    print("包：%s" % PKG)
    for fn in sorted(os.listdir(PKG)):
        p = os.path.join(PKG, fn)
        if os.path.isfile(p):
            sz = os.path.getsize(p)
            tot += sz
            print("  %-42s %9.2f MB" % (fn, sz / 1048576))
    for fn in sorted(os.listdir(os.path.join(PKG, "config"))):
        p = os.path.join(PKG, "config", fn)
        sz = os.path.getsize(p)
        tot += sz
        print("  config/%-35s %9.2f KB" % (fn, sz / 1024))
    print("  合计 %.2f MB（打包后约 1/5）" % (tot / 1048576))
    print("\n数据：train %d / val %d" % (n_train, n_val))
    print("配置：epochs=1，output 带 -v9t4（不覆盖 v9t）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
