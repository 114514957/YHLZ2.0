# -*- coding: utf-8 -*-
"""v14 = v13 的行**一条不改**，只重新配权（干净的单变量：只改权重）。

依据（v13 实测）：
  · 工具题 13 道全挂，答案多是"我记着/好，任务已添加/查过了"——**不调工具、用话糊过去**
  · 工具样本权重占比 8.9%(v9t10) → 6.9%(v13)；口述故事抢到 26.1%

v14 的新权：
  · 口述故事      2.0 → **1.0**（约 14%）
  · 工具调用样本  ×1.0 → **×2.0**（目标 15–18%）
  · 纪律/加固     ×1.0 → **×1.5**
  · 其余           不动
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(ROOT, "dist", "material_v13")
OUT = os.path.join(ROOT, "dist", "material_v14")
os.makedirs(os.path.join(OUT, "config"), exist_ok=True)

STORY_W = 1.0
# 纯乘法，不设下限——设了 max(w,1.0) 会把低权重行全抬到 1.0，
# 实测那样工具类会冲到 36%（过头），纯乘法 2.4 倍约 17%，正是目标区间。
TOOL_MULT = 2.4
DISC_MULT = 1.5


def classify(r: dict) -> str:
    ms = [m for m in (r.get("messages") or []) if isinstance(m, dict)]
    if any(m.get("tool_calls") for m in ms) or any(m.get("role") == "tool" for m in ms):
        return "tool"
    src = str(r.get("source") or "")
    if src.startswith("v11_dad_story"):
        return "story"
    if "discipline" in src or "harden" in src:
        return "disc"
    return "other"


stat = defaultdict(lambda: {"n": 0, "w": 0.0})
for split in ("train", "val"):
    src_p = os.path.join(SRC, "sft_persona_v13_%s.jsonl" % split)
    dst_p = os.path.join(OUT, "sft_persona_v14_%s.jsonl" % split)
    rows_out = []
    for ln in io.open(src_p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        kind = classify(r)
        w = float(r.get("weight") or 1.0)
        if kind == "story":
            w = STORY_W
        elif kind == "tool":
            w = w * TOOL_MULT
        elif kind == "disc":
            w = w * DISC_MULT
        r["weight"] = round(w, 3)
        rows_out.append(r)
        if split == "train":
            stat[kind]["n"] += 1
            stat[kind]["w"] += w
    io.open(dst_p, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out) + "\n")
    print("%s：%d 条 → %s" % (split, len(rows_out), os.path.basename(dst_p)))

tot = sum(v["w"] for v in stat.values())
print("\n=== v14 权重占比 ===")
for k, v in sorted(stat.items(), key=lambda x: -x[1]["w"]):
    zh = {"tool": "工具调用", "story": "口述故事", "disc": "纪律/加固", "other": "其余"}[k]
    print("   %-10s %5d 条｜Σw %8.1f｜占权重 %5.1f%%" % (zh, v["n"], v["w"], 100 * v["w"] / tot))
print("   Σ权重合计 %.1f" % tot)

# 配置：与 v13 一致，只换数据路径
cfg = json.load(io.open(os.path.join(SRC, "config", "finetune.gemma4.v13.json"),
                        encoding="utf-8"))
cfg["_说明"] = ("v14：与 v13 完全相同的行，只重新配权（故事 2.0→1.0、工具×2、纪律×1.5）。"
                "目的：修 v13 工具题 13 道全挂的问题。单变量＝只改权重。")
cfg["train_file"] = "/root/yh/material_v14/sft_persona_v14_train.jsonl"
cfg["val_file"] = "/root/yh/material_v14/sft_persona_v14_val.jsonl"
cfg["output_dir"] = "/root/autodl-tmp/models/lora/yuanheng-v14"
io.open(os.path.join(OUT, "config", "finetune.gemma4.v14.json"), "w",
        encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
print("\n配置：%s" % os.path.relpath(os.path.join(OUT, "config", "finetune.gemma4.v14.json"), ROOT))
