# -*- coding: utf-8 -*-
"""把「短答」「模板腔」两个缺口量化，给出达标状态。

口径：
  · 短答：台账 1078 —— 群里中位 10 字、54% ≤10 字；模型群里中位 59 字。
    这里看训练包里 assistant 台词的长度分布，能不能压住。
  · 模板腔：台账 1063/1086 —— 开头高频词会变成新模板腔；>2% 就算风险。
"""
from __future__ import annotations

import io
import json
import os
import re
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")

rows = []
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    with io.open(os.path.join(PACK, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

lens, by_src_short, opens = [], Counter(), Counter()
src_total = Counter()
n_short = n_all = 0
for r in rows:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"]
    if not a:
        continue
    ans = a[-1].strip()
    if not ans:
        continue
    src = str(r.get("source", "")).split(":")[0] or "?"
    lens.append(len(ans))
    src_total[src] += 1
    n_all += 1
    if len(ans) <= 20:
        n_short += 1
        by_src_short[src] += 1
    opens[ans[:2]] += 1

lens.sort()


def pct(q):
    return lens[min(len(lens) - 1, int(q * len(lens)))]


print("assistant 台词 %d 条" % n_all)
print("长度：中位 %d | p75 %d | p90 %d | ≤20 字 %d 条（%.1f%%）| ≤10 字 %.1f%%"
      % (statistics.median(lens), pct(0.75), pct(0.90), n_short,
         100 * n_short / n_all, 100 * sum(1 for x in lens if x <= 10) / n_all))
print("对照群里真话：中位 10 字、54%% ≤10 字（台账 1078）")

print("\n短答（≤20 字）按来源 Top8：")
for s, c in by_src_short.most_common(8):
    print("   %-14s %4d / %4d（%.0f%%）" % (s, c, src_total[s], 100 * c / src_total[s]))

print("\n模板腔开头（前 12）：")
watch = []
for t, c in opens.most_common(12):
    p = 100 * c / n_all
    flag = "⚠️" if p >= 2 else ""
    print("   %-6r %4d（%.1f%%）%s" % (t, c, p, flag))
    if p >= 2:
        watch.append({"opener": t, "n": c, "pct": round(p, 2)})

out = os.path.join(YH, "docs", "研究", "缺口量化_20261106.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump({"n": n_all, "median": statistics.median(lens), "p90": pct(0.90),
               "short20": n_short, "short_pct": round(100 * n_short / n_all, 1),
               "short10_pct": round(100 * sum(1 for x in lens if x <= 10) / n_all, 1),
               "short_by_src": dict(by_src_short), "watch_openers": watch},
              f, ensure_ascii=False, indent=1)
print("\n写出 %s" % out)
