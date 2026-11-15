# -*- coding: utf-8 -*-
"""量化：训练数据里这三个习惯各有多少条样本。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")

rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
print("样本 %d 条" % len(rows))

n_selfref = n_call = n_long = n_all3 = 0
by_src = Counter()
for r in rows:
    a = [m for m in r["messages"] if m.get("role") == "assistant"]
    if not a:
        continue
    t = a[-1].get("content") or ""
    sents = [s for s in re.split(r"[。！？\n]+", t) if s.strip()]
    has_self = any(x in t for x in ("本小姐", "老娘", "咱"))
    has_call = "老爹" in t
    has_long = bool(sents) and max(len(s) for s in sents) >= 35
    n_selfref += has_self
    n_call += has_call
    n_long += has_long
    if has_self and has_call and has_long:
        n_all3 += 1
    if has_self:
        by_src[str(r.get("source", "")).split(":")[0]] += 1

N = len(rows)
print("\n自称（本小姐/老娘/咱）：%d 条（%.1f%%）" % (n_selfref, 100 * n_selfref / N))
print("称呼老爹：             %d 条（%.1f%%）" % (n_call, 100 * n_call / N))
print("有一句 ≥35 字：        %d 条（%.1f%%）" % (n_long, 100 * n_long / N))
print("三者同时具备：         %d 条（%.2f%%）" % (n_all3, 100 * n_all3 / N))
print("\n带自称的样本来源：%s" % dict(by_src.most_common(8)))
