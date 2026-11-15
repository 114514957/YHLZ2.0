# -*- coding: utf-8 -*-
"""扫黄金样本库，按三个病分类（greet/scold/explain），并看 老爹/自称/长句 覆盖。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
GOLD = os.path.join(YH, "docs", "素材", "黄金样本.md")

md = io.open(GOLD, encoding="utf-8", errors="replace").read()
blocks = []
for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
    head, _, body = part.partition("\n")
    if "示例" in head:
        continue
    st = re.search(r"^\s*-\s*status\s*[:：]\s*(.*)$", body, re.M)
    status = st.group(1).strip() if st else ""
    if status == "drop":
        continue
    segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
    u = a = ""
    for i in range(1, len(segs) - 1, 2):
        title, text = segs[i].strip(), segs[i + 1].strip()
        if "老爹" in title:
            u = text
        elif "元亨" in title:
            a = text
    if u and a:
        blocks.append({"id": head.strip(), "status": status, "u": u, "a": a})

print("黄金块（非 drop）：%d" % len(blocks))
GREET = re.compile(r"(我回来了|回来啦|到家了|回家|我回来啦)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气)")
EXPLAIN = re.compile(r"(讲讲|说说|说给我听|怎么回事|凭什么|你怎么看|解释)")

cnt = {"greet": 0, "scold": 0, "explain": 0, "call老爹": 0, "自称": 0, "长句35": 0}
hits = {"greet": [], "scold": [], "explain": []}
for b in blocks:
    u, a = b["u"], b["a"]
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    if GREET.search(u):
        cnt["greet"] += 1
        hits["greet"].append(b)
    if SCOLD.search(u):
        cnt["scold"] += 1
        hits["scold"].append(b)
    if EXPLAIN.search(u):
        cnt["explain"] += 1
        hits["explain"].append(b)
    if "老爹" in a:
        cnt["call老爹"] += 1
    if any(x in a for x in ("本小姐", "老娘", "咱")):
        cnt["自称"] += 1
    if sents and max(len(s) for s in sents) >= 35:
        cnt["长句35"] += 1

print("分布：%s" % cnt)
for k in ("greet", "scold", "explain"):
    print("\n[%s] %d 条" % (k, len(hits[k])))
    for b in hits[k][:4]:
        print("   问：%s\n   答：%s" % (b["u"][:40], b["a"][:80].replace("\n", " ")))
