# -*- coding: utf-8 -*-
"""包里到底有没有「我是程序/模型」这类台词：按词频和样例看。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")

rows = []
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    with io.open(os.path.join(PACK, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

KEY = ["程序", "大模型", "语言模型", "AI", "人工智能", "机器人", "意识", "灵魂"]
cnt = Counter()
samples: dict[str, list] = {k: [] for k in KEY}
for r in rows:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"]
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    if not a:
        continue
    ans = a[-1]
    for k in KEY:
        if k in ans:
            cnt[k] += 1
            if len(samples[k]) < 6:
                samples[k].append((q.strip(), ans.strip(), str(r.get("source", "")).split(":")[0]))

print("assistant 台词里出现这些词的有：")
for k, v in cnt.most_common():
    print("   %-8s %4d 条" % (k, v))

for k in ("程序", "大模型", "语言模型", "意识"):
    print("\n=== 含「%s」的样例 ===" % k)
    for q, a, src in samples[k]:
        print("  [%s] Q: %s" % (src, q[:36]))
        print("        A: %s" % a[:80])
