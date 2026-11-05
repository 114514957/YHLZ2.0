# -*- coding: utf-8 -*-
"""素材画像：把 6 份素材的 5999 条答案统一统计一遍，看看到底缺什么、多什么。

只读，不改素材。
"""
from __future__ import annotations

import io
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mine_samples as M  # noqa: E402

rows = []
for fn in M.FILES:
    p = os.path.join(M.MAT, fn)
    if not os.path.exists(p):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            rows.append((fn, bid, q.strip(), a.strip()))

n = len(rows)
lens = sorted(len(a) for _, _, _, a in rows)
tic = Counter()
for _, _, _, a in rows:
    for t in ("哇哈哈", "哇", "啊哈", "本小姐", "哦", "嗯", "哈"):
        if a.startswith(t):
            tic[t] += 1
            break
short = sum(1 for l in lens if l <= 12)
mid = sum(1 for l in lens if 12 < l <= 40)
long_ = sum(1 for l in lens if l > 40)

print("答案总数 %d" % n)
print("长度：中位 %d 字 | ≤12 字 %d (%.1f%%) | 13-40 %d (%.1f%%) | >40 %d (%.1f%%)"
      % (lens[n // 2], short, 100 * short / n, mid, 100 * mid / n, long_, 100 * long_ / n))
print("模板腔开口 %d 条（%.1f%%）：%s"
      % (sum(tic.values()), 100 * sum(tic.values()) / n,
         ", ".join("%s:%d" % kv for kv in tic.most_common(8))))

# 短问答配对里，问句只有 1-8 字的（寒暄的真实来源）
short_q = [r for r in rows if len(r[2]) <= 8 and len(r[3]) <= 20]
print("\n短问短答（问≤8字 且 答≤20字）：%d 条" % len(short_q))
seen = set()
for fn, bid, q, a in short_q[:25]:
    key = q
    if key in seen:
        continue
    seen.add(key)
    print("   %-14s/%-12s %-10s → %s" % (os.path.basename(fn)[:12], bid[:12], q, a[:26]))
