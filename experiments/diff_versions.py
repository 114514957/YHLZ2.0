# -*- coding: utf-8 -*-
"""v9t5 → v9t11 配置逐项 diff，找出 25→42→48 那两次跳变到底改了什么。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

VERS = ["retrain_pkg_gemma_v9t5", "retrain_pkg_gemma_v9t6", "retrain_pkg_gemma_v9t7",
        "retrain_pkg_gemma_v9t8", "retrain_pkg_gemma_v9t9", "retrain_pkg_gemma_v9t10",
        "retrain_pkg_gemma_v9t11", "retrain_pkg_gemma_v10u", "retrain_pkg_gemma_v11"]

cfgs = {}
for v in VERS:
    g = glob.glob(os.path.join(ROOT, "dist", v, "config", "*.json"))
    if g:
        cfgs[v] = json.load(open(g[0], encoding="utf-8-sig"))

KEYS = ["lr", "epochs", "batch_size", "grad_accum", "max_seq_len", "lora_r",
        "lora_alpha", "warmup_ratio", "lr_scheduler_type", "optim",
        "load_in_4bit", "mask_prompt", "bnb_compute_dtype", "gradient_checkpointing"]
print("%-26s %s" % ("版本", " ".join("%-10s" % k[:10] for k in KEYS)))
for v, c in cfgs.items():
    cells = []
    for k in KEYS:
        x = c.get(k)
        if isinstance(x, bool):
            x = "Y" if x else "N"
        cells.append("%-10s" % str(x)[:10])
    print("%-26s %s" % (v.replace("retrain_pkg_gemma_", "").replace("retrain_pkg_", ""),
                        " ".join(cells)))

print("\n=== 逐版差异（只打印与上一版不同的项）===")
prev = None
for v, c in cfgs.items():
    if prev is not None:
        diffs = []
        for k in KEYS:
            a, b = prev.get(k), c.get(k)
            if a != b:
                diffs.append("%s: %s → %s" % (k, a, b))
        print("  %-30s %s" % (v.replace("retrain_pkg_gemma_", ""),
                              "｜".join(diffs) or "（无变化）"))
    prev = c

print("\n=== 训练数据量（config.train_file 行数）===")
for v, c in cfgs.items():
    tf = str(c.get("train_file") or "")
    base = os.path.basename(tf)
    local = glob.glob(os.path.join(ROOT, "dist", v, base))
    n = "?"
    if local:
        n = sum(1 for x in io.open(local[0], encoding="utf-8") if x.strip())
    print("  %-30s %-46s %s 条" % (v.replace("retrain_pkg_gemma_", ""), base[:46], n))
