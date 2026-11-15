# -*- coding: utf-8 -*-
"""用 v4 补丁重建训练包：短 replay + v4 补丁，seq 640。"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")
PATCH = os.path.join(YH, "dist", "style_patch_v4", "patch.jsonl")
REPLAY = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
OUT = os.path.join(YH, "dist", "retrain_pkg_stylepatch")
rng = random.Random(20261112)

shutil.copy2(os.path.join(SRC, "finetune_train.py"), os.path.join(OUT, "finetune_train.py"))

patch = [json.loads(x) for x in io.open(PATCH, encoding="utf-8") if x.strip()]

replay = []
p = os.path.join(REPLAY, "sft_persona_v10u_train.jsonl")
if os.path.exists(p):
    for x in io.open(p, encoding="utf-8"):
        if not x.strip():
            continue
        r = json.loads(x)
        total = sum(len(m.get("content") or "") for m in r["messages"])
        if total <= 700:                      # 只留短样本，免得再被判超长
            replay.append({"messages": r["messages"], "source": "replay", "weight": 0.3})
rng.shuffle(replay)
replay = replay[:200]
print("短 replay：%d 条" % len(replay))

allr = patch + replay
rng.shuffle(allr)
n_val = max(16, len(allr) // 10)
with io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[:-n_val]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with io.open(os.path.join(OUT, "sft_persona_patch_val.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[-n_val:]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

cfg = json.load(io.open(os.path.join(OUT, "config", "finetune.stylepatch.json"),
                        encoding="utf-8"))
cfg["max_seq_len"] = 640
cfg["output_dir"] = "../models/lora/yuanheng-stylepatch4"
cfg["_说明"] = "stylepatch v4：153 条补丁（含 24 个故事单轮长句）+ 200 短 replay@0.3；seq 640。"
with io.open(os.path.join(OUT, "config", "finetune.stylepatch.json"), "w",
             encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)

tr = sum(1 for x in io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"),
                           encoding="utf-8") if x.strip())
print("train %d｜val %d｜步数 %d" % (tr, n_val, (-(-tr // 8)) * 2))
