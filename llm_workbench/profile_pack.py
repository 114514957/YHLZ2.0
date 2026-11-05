# -*- coding: utf-8 -*-
"""体检训练包：assistant 台词的长度、开头、自称、反问、模板腔、客服腔，按来源拆。

目的：不猜「训出来会像什么」，直接按数据分布说。
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
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\dist\retrain_pkg_gemma_v9t7"

SELF = ["本小姐", "老娘", "元亨", "咱", "我"]
TIC = ["哇哈哈", "哇", "啊哈", "哈哈", "嘿嘿", "哎呀", "哎呦", "哎哟"]
SVC = ["为您", "需要我", "有什么可以帮", "要不要我", "还有什么", "帮您"]


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


rows = read(os.path.join(D, "sft_persona_v9t6t_train.jsonl")) + \
       read(os.path.join(D, "sft_persona_v9t6t_val.jsonl"))

lines, opens, tail_q, tic, svc = [], Counter(), 0, Counter(), 0
selfc = Counter()
by_src: dict[str, list] = {}

for r in rows:
    msgs = r.get("messages") or []
    asst = [m["content"] for m in msgs if m.get("role") == "assistant"]
    if not asst:
        continue
    a = asst[-1].strip()
    if not a:
        continue
    src = str(r.get("source", "")).split(":")[0] or "?"
    lines.append(len(a))
    by_src.setdefault(src, []).append(len(a))
    opens[a[:2]] += 1
    if a.rstrip("”\"'」』）) ")[-1:] in ("？", "?"):
        tail_q += 1
    for t in TIC:
        if a.startswith(t):
            tic[t] += 1
            break
    if any(x in a for x in SVC):
        svc += 1
    for s in SELF:
        if s in a:
            selfc[s] += 1

n = len(lines)
lines_sorted = sorted(lines)
def pct(q):
    return lines_sorted[min(n - 1, int(q * n))]

print("assistant 台词 %d 条（取每条最后一句）" % n)
print("长度：中位 %d | p75 %d | p90 %d | ≤20字 %.1f%% | >100字 %.1f%%"
      % (statistics.median(lines), pct(0.75), pct(0.90),
         100 * sum(1 for x in lines if x <= 20) / n,
         100 * sum(1 for x in lines if x > 100) / n))
print("反问收尾：%.1f%%" % (100 * tail_q / n))
print("模板腔开头：%.1f%%  %s" % (100 * sum(tic.values()) / n,
                              ", ".join("%s:%d" % kv for kv in tic.most_common(8))))
print("客服腔：%.1f%%" % (100 * svc / n))
print("自称出现：%s" % ", ".join("%s:%d" % (k, selfc[k]) for k in SELF))
print("\n开头两字 Top 12：%s" % ", ".join("%s×%d" % kv for kv in opens.most_common(12)))
print("\n按来源（中位字数 / 条数）：")
for src, arr in sorted(by_src.items(), key=lambda x: -len(x[1]))[:12]:
    print("   %-14s %5d 条 | 中位 %3d" % (src, len(arr), statistics.median(arr)))
