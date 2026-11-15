# -*- coding: utf-8 -*-
"""找「每一版都挂」的题——训练到底在哪几道题上从来没长进。"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\docs\研究\版本迭代表_20261107.json"
d = json.load(io.open(P, encoding="utf-8"))

# 去重：同一个 tag 的多份记录只算一次（取第一份）
seen, rows = set(), []
for r in d["rows"]:
    key = r["tag"]
    if key in seen:
        continue
    seen.add(key)
    rows.append(r)

print("去重后 %d 个配置\n" % len(rows))
cnt = Counter()
for r in rows:
    for f in r["fails"]:
        cnt[f] += 1

n = len(rows)
print("%-6s %-8s %s" % ("题号", "挂的版本数", "占比"))
for q, c in cnt.most_common(20):
    flag = "  ← 每版都挂" if c == n else ""
    print("%-6s %-8d %d/%d%s" % (q, c, c, n, flag))

always = [q for q, c in cnt.items() if c == n]
print("\n**每版必挂（%d 道）**：%s" % (len(always), ",".join(sorted(always))))
print("理论上限：%d/56" % (56 - len(always)))

# 每个配置的「非必挂失败」= 本版特有的退步
print("\n每个配置的特有失败（排除必挂）：")
for r in sorted(rows, key=lambda x: -x["ok"]):
    extra = [f for f in r["fails"] if f not in always]
    print("  %-20s %2d/%d  特有:%s" % (r["tag"][:20], r["ok"], r["total"],
                                     ",".join(extra) or "-"))
