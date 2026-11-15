# -*- coding: utf-8 -*-
"""查「老爹口述的故事」到底有几块、块头长什么样。"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
SKIP = {"_废弃"}

heads = []
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
            if head.startswith("故事"):
                heads.append((head, os.path.relpath(p, MAT)))

print("块头以「故事」开头共 %d 个" % len(heads))
c = Counter(h for h, _ in heads)
for h, n in sorted(c.items()):
    print("   %-40s ×%d" % (h[:40], n))

print("\n匹配 老爹口述 正则的：")
pat = re.compile(r"^故事-(?:[1-5]｜|黄河钓鱼)")
for h, f in heads:
    if pat.match(h):
        print("   ✅ %-36s [%s]" % (h[:36], f))
print("\n不匹配但像海带/钓鱼的：")
for h, f in heads:
    if ("海带" in h or "钓鱼" in h) and not pat.match(h):
        print("   ⚠️ %-36s [%s]" % (h[:36], f))
