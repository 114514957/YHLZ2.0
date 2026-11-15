# -*- coding: utf-8 -*-
"""盘素材：一共多少条、哪些进了 v9t10 的包、还差多少没进。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FT = os.path.join(YH, "data", "finetune")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")

# 1. 素材总表
mp = os.path.join(FT, "materials.json")
if os.path.exists(mp):
    m = json.load(io.open(mp, encoding="utf-8"))
    if isinstance(m, dict):
        print("materials.json：dict，键 %s" % list(m.keys())[:8])
        for k, v in list(m.items())[:5]:
            print("   %s: %s" % (k, (str(v)[:80])))
    else:
        print("materials.json：list，%d 条" % len(m))
        print("   样例键：%s" % sorted(m[0].keys()) if m else "")
else:
    print("没有 materials.json")

# 2. 包里已有的
rows = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
print("\n包内 %d 条｜来源分布（前 12）：" % len(rows))
for s, c in Counter(str(r.get("source", "")).split(":")[0] for r in rows).most_common(12):
    print("   %-18s %d" % (s, c))

# 3. 黄金样本
gp = os.path.join(FT, "golden_candidates.jsonl")
if os.path.exists(gp):
    g = [json.loads(x) for x in io.open(gp, encoding="utf-8") if x.strip()]
    print("\ngolden_candidates.jsonl：%d 条｜包内 golden %d 条"
          % (len(g), sum(1 for r in rows if str(r.get("source", "")).startswith("golden"))))
