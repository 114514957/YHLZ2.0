# -*- coding: utf-8 -*-
"""找长文答案（≥4 句且长句率≥40%），看它们的用户话是什么，再判断是不是故事类。"""
from __future__ import annotations

import glob
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

longs = []
for r in rows:
    us = [m for m in r["messages"] if m.get("role") == "user"]
    as_ = [m for m in r["messages"] if m.get("role") == "assistant"]
    if not us or not as_:
        continue
    u, a = us[-1]["content"], as_[-1]["content"]
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    if len(sents) < 4:
        continue
    ratio = sum(1 for s in sents if len(s) >= 35) / len(sents)
    if ratio >= 0.4:
        longs.append({"src": str(r.get("source", "")), "u": u, "a": a, "ratio": ratio})

print("长文样本（≥4 句且长句率≥40%%）：%d 条（%.1f%%）"
      % (len(longs), 100 * len(longs) / len(rows)))
print("来源：%s" % dict(Counter(x["src"].split(":")[0] for x in longs).most_common(8)))

print("\n按用户话首词看类型：")
kw = Counter()
for x in longs:
    for k in ("故事", "讲讲", "说说", "怎么", "为什么", "解释", "评价", "聊聊", "写"):
        if k in x["u"]:
            kw[k] += 1
print("   %s" % dict(kw.most_common()))

print("\n样例（用户话 → 答案开头）：")
for x in longs[:8]:
    print("   [%-12s] %s" % (x["src"].split(":")[0], x["u"][:40]))
    print("               %s…" % x["a"][:80].replace("\n", " "))
