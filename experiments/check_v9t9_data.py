# -*- coding: utf-8 -*-
"""核对 v9t9 现在用的那份数据（= v9t6 的）到底齐不齐、权重合不合理。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def load(pkg):
    d = os.path.join(YH, "dist", pkg)
    rows = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".jsonl"):
            with io.open(os.path.join(d, fn), encoding="utf-8") as f:
                rows += [json.loads(x) for x in f if x.strip()]
    return rows


def report(pkg, rows):
    n = len(rows)
    eff = 0.0
    by = defaultdict(lambda: [0, 0.0])
    for r in rows:
        w = float(r.get("weight", 1.0) or 1.0)
        src = str(r.get("source", "")).split(":")[0] or "?"
        eff += w
        by[src][0] += 1
        by[src][1] += w
    print("\n== %s：%d 条｜Σw = %.0f" % (pkg, n, eff))
    for s, (c, w) in sorted(by.items(), key=lambda x: -x[1][1]):
        print("   %-18s %5d 条｜Σw %6.1f｜占有效 %5.2f%%" % (s, c, w, 100 * w / eff))
    return eff, by


v6 = load("retrain_pkg_gemma_v9t6")
v8 = load("retrain_pkg_gemma_v9t8")
report("v9t9 现在用的 = v9t6 数据", v6)
report("v9t8（最新，含所有补丁）", v8)

# 关键差异
s6 = {str(r.get("source", "")).split(":")[0] for r in v6}
s8 = {str(r.get("source", "")).split(":")[0] for r in v8}
print("\n=== v9t9 缺什么（v9t8 有、v9t6 没有的来源）===")
for s in sorted(s8 - s6):
    c = sum(1 for r in v8 if str(r.get("source", "")).startswith(s))
    print("   %-18s %d 条" % (s, c))

print("\n=== v9t9 多什么（v9t6 有、后来被删掉的）===")
for s in sorted(s6 - s8):
    c = sum(1 for r in v6 if str(r.get("source", "")).startswith(s))
    print("   %-18s %d 条" % (s, c))

# 「记得。」那种模板腔还在不在
tic = sum(1 for r in v6
          if any(m["role"] == "assistant" and m["content"].startswith("记得。")
                 for m in r["messages"]))
print("\nv9t6 里以「记得。」开头的样本：**%d 条**（这是 v9t7 专门删掉的模板腔）" % tic)
