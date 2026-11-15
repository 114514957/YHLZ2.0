# -*- coding: utf-8 -*-
"""盘点历史训练数据来源：配置 / 日志 / CSV / 摘要。"""
from __future__ import annotations

import glob
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=== 训练配置（dist/retrain_pkg_*）===")
for p in sorted(glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_*", "config", "*.json"))):
    rel = os.path.relpath(p, ROOT)
    print("   %-62s %6d B" % (rel[-62:], os.path.getsize(p)))

print("\n=== 训练器（含 loss/lr 公式的地方）===")
for p in sorted(glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_*", "finetune_train.py"))):
    print("   %-62s %6d B" % (os.path.relpath(p, ROOT)[-62:], os.path.getsize(p)))
for p in sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))):
    n = os.path.basename(p)
    if any(k in n for k in ("train", "dpo", "finetune")):
        print("   %-62s %6d B" % (os.path.relpath(p, ROOT)[-62:], os.path.getsize(p)))

print("\n=== 日志 / CSV / 摘要（本地已有）===")
pats = [
    "cache/**/train_log.csv", "cache/**/train_summary.json",
    "models/lora/**/train_log.csv", "models/lora/**/train_summary.json",
    "cache/logs/*train*.log", "cache/*train*.log", "cache/*.log",
    "cache/stylepatch*.log", "cache/launch_v11.log", "cache/wait_v11.log",
]
seen = set()
for pat in pats:
    for p in sorted(glob.glob(os.path.join(ROOT, pat), recursive=True)):
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        sz = os.path.getsize(p)
        if sz < 200:
            continue
        txt = io.open(p, encoding="utf-8", errors="replace").read(4000)
        has = [k for k in ("loss", "grad_norm", "learning_rate", "'lr'", "eval_loss")
               if k in txt]
        if has:
            print("   %-58s %8d B  (%s)" % (os.path.relpath(p, ROOT)[-58:], sz,
                                            ",".join(has[:4])))
