# -*- coding: utf-8 -*-
"""量化「权重问题」：v9t7 → v9t8 加了 287 条 weight 0.8 的素材，
各类的「有效条数」(Σ weight) 与占比怎么变的，工具类被稀释了多少。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def load(ver):
    d = os.path.join(YH, "dist", "retrain_pkg_gemma_%s" % ver)
    rows = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".jsonl") and ("train" in fn or "val" in fn):
            with io.open(os.path.join(d, fn), encoding="utf-8") as f:
                rows += [json.loads(x) for x in f if x.strip()]
    return rows


def stats(rows):
    n = len(rows)
    eff = 0.0
    by = defaultdict(lambda: [0, 0.0])   # src -> [条数, Σweight]
    tool_calls = 0
    for r in rows:
        w = float(r.get("weight", 1.0) or 1.0)
        src = str(r.get("source", "")).split(":")[0] or "?"
        eff += w
        by[src][0] += 1
        by[src][1] += w
        if any(m.get("role") == "assistant" and m.get("content") for m in []) or \
           r.get("tool_calls") or any("tool_calls" in m for m in r["messages"]):
            # 训练包里工具样本是空 assistant 文本或带 tool_calls，这里按 source 名兜底统计
            pass
    return n, eff, by


for ver in ("v9t7", "v9t8"):
    rows = load(ver)
    n, eff, by = stats(rows)
    print("== %s：%d 条，Σweight=%.0f" % (ver, n, eff))
    key = [("discipline", "工具纪律"), ("identity", "身份"), ("refusal", "安全拒绝"),
           ("internal_refusal", "内部拒绝"), ("material_full", "全量素材新增")]
    for src, label in key:
        c, w = by.get(src, [0, 0.0])
        print("   %-14s %4d 条 | Σw=%6.1f | 占总有效 %.2f%%" % (label, c, w, 100 * w / eff))
    # 前三来源
    print("   其它大头：%s" % ", ".join("%s %d条/Σw%.0f" % (s, v[0], v[1])
                                     for s, v in sorted(by.items(), key=lambda x: -x[1][1])[:5]))
    print()

# 新增那 287 条里有没有工具调用样本
v7 = load("v9t7")
v8 = load("v9t8")
h7 = {r.get("content_hash") for r in v7}
new = [r for r in v8 if r.get("content_hash") not in h7]
print("v9t8 相对 v9t7 新增 %d 条" % len(new))
w = Counter(float(r.get("weight", 1.0) or 1.0) for r in new)
print("  权重分布：%s" % dict(w))
src = Counter(str(r.get("source", "")).split(":")[0] for r in new)
print("  来源：%s" % dict(src))
# 其中带工具调用的
tool = [r for r in new if any(isinstance(m, dict) and m.get("role") == "tool" for m in r["messages"])
        or any("tool_calls" in (m or {}) for m in r["messages"])]
print("  带工具调用：%d 条" % len(tool))
