# -*- coding: utf-8 -*-
"""风格补丁 v2：原文 + 黄金样本，专治 st02（长句）/st03（自称）/st05（叫老爹）。

来源与权重：
  greet   （问候→带老爹）  原文 2 条     ×4.0   ← 全库最缺
  scold   （被凶→自称）    原文 27 条    ×2.0
  explain （讲讲→长句）    原文 46 + 黄金 4 ×1.5
  golden_long（黄金里 ≥35 字长句的块）22 条 ×1.5   ← 这一批是"用黄金样本补"的主体
  golden_call（黄金里答带老爹）3 条        ×2.0
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
MAT = os.path.join(YH, "docs", "素材")
GOLD = os.path.join(MAT, "黄金样本.md")
OUT = os.path.join(YH, "dist", "style_patch_v2")

GREET = re.compile(r"(我回来了|回来啦|到家了|回家|我回来啦)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气)")
EXPLAIN = re.compile(r"(讲讲|说说|说给我听|怎么回事|凭什么|你怎么看|解释)")
SELFREF = ("本小姐", "老娘", "咱")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手)")


def long_enough(a, n=35):
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    return bool(sents) and max(len(s) for s in sents) >= n


def parse_md(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        if "示例" in head:
            continue
        if re.search(r"^\s*-\s*status\s*[:：]\s*drop", body, re.M):
            continue
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        u = a = ""
        for i in range(1, len(segs) - 1, 2):
            title, text = segs[i].strip(), segs[i + 1].strip()
            if "老爹" in title or "用户" in title:
                u = text
            elif "元亨" in title:
                a = text
        if u and a:
            out.append([{"role": "user", "content": u},
                        {"role": "assistant", "content": a}])
    return out


buckets = Counter()
items = []
seen = set()


def add(msgs, bucket, weight):
    u = msgs[0]["content"]
    a = msgs[-1]["content"]
    if BADCALL.search(a):
        return
    key = (u.strip()[:40], a.strip()[:40])
    if key in seen:
        return
    seen.add(key)
    items.append({"messages": msgs, "source": "patch_" + bucket, "weight": weight})
    buckets[bucket] += 1


# ① 训练包原文
rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        rows += [json.loads(x)["messages"] for x in io.open(p, encoding="utf-8") if x.strip()]
# ② 素材 md
if os.path.isdir(MAT):
    for f in sorted(os.listdir(MAT)):
        if f.endswith(".md") and not f.endswith(("_改名块头前.md", "_压缩前.md")) \
                and f != "黄金样本.md":
            rows += parse_md(os.path.join(MAT, f))

for msgs in rows:
    us = [m for m in msgs if m.get("role") == "user"]
    as_ = [m for m in msgs if m.get("role") == "assistant"]
    if not us or not as_:
        continue
    u, a = us[-1]["content"], as_[-1]["content"]
    if GREET.search(u) and "老爹" in a and len(a) <= 80:
        add([{"role": "user", "content": u}, {"role": "assistant", "content": a}],
            "greet", 4.0)
    elif SCOLD.search(u) and any(x in a for x in SELFREF):
        add([{"role": "user", "content": u}, {"role": "assistant", "content": a}],
            "scold", 2.0)
    elif EXPLAIN.search(u) and long_enough(a):
        add([{"role": "user", "content": u}, {"role": "assistant", "content": a}],
            "explain", 1.5)

# ③ 黄金样本
if os.path.exists(GOLD):
    for msgs in parse_md(GOLD):
        u, a = msgs[0]["content"], msgs[-1]["content"]
        if long_enough(a):
            add(msgs, "golden_long", 1.5)
        if "老爹" in a:
            add(msgs, "golden_call", 2.0)

os.makedirs(OUT, exist_ok=True)
with io.open(os.path.join(OUT, "patch.jsonl"), "w", encoding="utf-8") as f:
    for x in items:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")

print("补丁 v2：%d 条｜Σw %.0f" % (len(items), sum(x["weight"] for x in items)))
for k, v in buckets.most_common():
    w = sum(x["weight"] for x in items if x["source"] == "patch_" + k)
    print("  %-12s %3d 条｜Σw %5.1f" % (k, v, w))
