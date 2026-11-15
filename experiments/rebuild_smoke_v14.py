# -*- coding: utf-8 -*-
"""用 v14 的权重重抽冒烟 60 条（同种子，保证可复现），并校验配置。"""
from __future__ import annotations

import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
V14 = os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_train.jsonl")
OUT_DIR = os.path.join(ROOT, "dist", "material_v14", "smoke")
os.makedirs(OUT_DIR, exist_ok=True)

rows = [json.loads(x) for x in io.open(V14, encoding="utf-8", errors="replace") if x.strip()]
random.Random(20261114).shuffle(rows)
pick = rows[:60]
smoke = os.path.join(OUT_DIR, "smoke60_train.jsonl")
io.open(smoke, "w", encoding="utf-8").write(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in pick) + "\n")

cfg = json.load(io.open(os.path.join(ROOT, "dist", "material_v14", "config",
                                     "finetune.gemma4.v14.json"), encoding="utf-8"))
cfg.update({
    "_说明": "v14 冒烟：60 条 ×6 epoch，lr 1e-4。只验训练通路与梯度，不出分。",
    "train_file": "/root/yh/material_v14/smoke60_train.jsonl",
    "output_dir": "/root/autodl-tmp/models/lora/yuanheng-v14-smoke",
    "epochs": 6.0,
    "lr": 0.0001,
    "logging_steps": 5,
})
out_cfg = os.path.join(OUT_DIR, "smoke60.json")
io.open(out_cfg, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))

tool_n = sum(1 for r in pick
             if any(m.get("tool_calls") for m in r["messages"])
             or any(m.get("role") == "tool" for m in r["messages"]))
print("冒烟子集：%d 条（其中工具类 %d 条）" % (len(pick), tool_n))
print("  %s" % os.path.relpath(smoke, ROOT))
print("  %s" % os.path.relpath(out_cfg, ROOT))
print("  epochs=%s lr=%s attn=%s" % (cfg["epochs"], cfg["lr"], cfg["attn_implementation"]))
