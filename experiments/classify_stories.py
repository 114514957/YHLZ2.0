# -*- coding: utf-8 -*-
"""精确分类所有「故事-」块：
   A 老爹口述系列（故事-<名字>-<序号>｜）      ← 权重最高
   B 老爹早期两批（故事-1..5 海带、故事-黄河钓鱼-*）
   C 扩写改写（故事-201..230，从对话块扩写）
   D 试作/测试（故事-001/101..105、2XX 模板）
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
SKIP = {"_废弃"}

named = re.compile(r"^故事-([^\d｜\s][^｜]*?)-\d+｜")     # 故事-黄河钓鱼-3｜出发
early = re.compile(r"^故事-([1-5])｜")                    # 故事-3｜吃海带的一周
expanded = re.compile(r"^故事-([2-9]\d{2})｜")            # 故事-201｜…
draft = re.compile(r"^故事-(00\d|1\d\d)｜|^故事-2XX｜")   # 试作/测试/模板

groups = {"A_老爹口述系列": [], "B_早期海带/钓鱼": [], "C_扩写": [], "D_试作测试": [], "E_未分类": []}
series = Counter()

for dirpath, dirs, files in os.walk(MAT):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if not f.endswith(".md"):
            continue
        p = os.path.join(dirpath, f)
        try:
            md = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
            head = part.partition("\n")[0].strip()
            if not head.startswith("故事"):
                continue
            body = part
            rec = (head, os.path.relpath(p, MAT))
            if named.match(head) or early.match(head):
                if named.match(head):
                    groups["A_老爹口述系列"].append(rec)
                    series[named.match(head).group(1) + "-系列"] += 1
                else:
                    groups["B_早期海带/钓鱼"].append(rec)
            elif expanded.match(head):
                groups["C_扩写"].append(rec)
            elif draft.match(head):
                groups["D_试作测试"].append(rec)
            else:
                groups["E_未分类"].append(rec)

for k, v in groups.items():
    print("%-16s %5d 块" % (k, len(v)))

print("\nA 组里有多少个系列（前 30）：")
for s, n in series.most_common(30):
    print("   %-16s %3d 块" % (s.replace("-系列", ""), n))
print("   共 %d 个系列" % len(series))

print("\nE 组未分类的块头样例（前 10）：")
for h, f in groups["E_未分类"][:10]:
    print("   %-40s [%s]" % (h[:40], f))
