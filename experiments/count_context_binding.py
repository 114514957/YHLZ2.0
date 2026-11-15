# -*- coding: utf-8 -*-
"""查上下文绑定：被凶场景里的自称率、问候场景里的「老爹」率、'讲讲'场景的长句率。"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")

rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]

SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|你他妈|有病|烦死|什么态度|脾气)")
GREET = re.compile(r"(我回来了|回来了|到家了|我回来啦)")
EXPLAIN = re.compile(r"(讲讲|说说|说给我听|怎么回事|凭什么|你怎么看|解释)")

stat = {"被凶": [0, 0], "问候": [0, 0], "讲讲": [0, 0]}
ex = {"被凶": [], "问候": [], "讲讲": []}
for r in rows:
    us = [m for m in r["messages"] if m.get("role") == "user"]
    as_ = [m for m in r["messages"] if m.get("role") == "assistant"]
    if not us or not as_:
        continue
    u = us[-1].get("content") or ""
    a = as_[-1].get("content") or ""
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    if SCOLD.search(u):
        stat["被凶"][0] += 1
        if any(x in a for x in ("本小姐", "老娘", "咱")):
            stat["被凶"][1] += 1
            if len(ex["被凶"]) < 3:
                ex["被凶"].append((u[:30], a[:80]))
    if GREET.search(u):
        stat["问候"][0] += 1
        if "老爹" in a:
            stat["问候"][1] += 1
            if len(ex["问候"]) < 3:
                ex["问候"].append((u[:30], a[:80]))
    if EXPLAIN.search(u):
        stat["讲讲"][0] += 1
        if sents and max(len(s) for s in sents) >= 35:
            stat["讲讲"][1] += 1
            if len(ex["讲讲"]) < 3:
                ex["讲讲"].append((u[:30], a[:80]))

for k, (tot, hit) in stat.items():
    print("%s：场景样本 %4d 条｜满足要求的 %3d 条（%.1f%%）"
          % (k, tot, hit, 100 * hit / max(1, tot)))
    for u, a in ex[k]:
        print("   问：%s\n   答：%s" % (u, a))
    print()
