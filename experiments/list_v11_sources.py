# -*- coding: utf-8 -*-
"""列出 v11 的所有来源，标出哪些属于「闸门类/工具类」，准备按代价改权重。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(YH, "dist", "retrain_pkg_gemma_v11")

cnt = Counter()
wsum = Counter()
for fn in ("sft_persona_v11_train.jsonl", "sft_persona_v11_val.jsonl"):
    for x in io.open(os.path.join(P, fn), encoding="utf-8"):
        if not x.strip():
            continue
        r = json.loads(x)
        s = str(r.get("source", "")).split(":")[0] or "?"
        cnt[s] += 1
        wsum[s] += float(r.get("weight", 1.0) or 1.0)

total = sum(wsum.values())
print("%-22s %6s %10s %8s" % ("来源", "条数", "Σw", "占比"))
for s, w in wsum.most_common():
    print("%-22s %6d %10.1f %7.2f%%" % (s, cnt[s], w, 100 * w / total))
print("\n合计 %d 条｜Σw %.0f" % (sum(cnt.values()), total))

GATE = {"refusal", "harden", "internal_refusal", "identity_ai"}
TOOL = {s for s in cnt if "tool" in s.lower() or "discipline" in s.lower()}
print("\n闸门类来源：%s" % sorted(GATE & set(cnt)))
print("工具类来源：%s" % sorted(TOOL))
g = sum(wsum[s] for s in GATE & set(cnt))
t = sum(wsum[s] for s in TOOL)
print("闸门类 Σw %.1f（%.2f%%）｜工具类 Σw %.1f（%.2f%%）"
      % (g, 100 * g / total, t, 100 * t / total))
