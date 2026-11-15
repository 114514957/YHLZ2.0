# -*- coding: utf-8 -*-
"""建风格补丁数据集：针对 st02/st03/st05 三个病，只用原文。

三个桶：
  greet  —— 用户说「回来了/到家了」，元亨答里带「老爹」
  scold  —— 用户凶/骂，元亨用「本小姐/老娘/咱」自称
  explain—— 用户要「讲讲/说说」，元亨有一句 ≥35 字
每个桶从 训练包 + docs/素材 的 md 里找原文，去重后加权（缺口大的桶权重高）。
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
OUT = os.path.join(YH, "dist", "style_patch_v1")

GREET = re.compile(r"(我回来了|回来啦|到家了|我回来啦|回家了)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气|你他妈)")
EXPLAIN = re.compile(r"(讲讲|说说|说给我听|怎么回事|凭什么|你怎么看|解释)")
SELFREF = ("本小姐", "老娘", "咱")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手)")


def ok_greet(u, a):
    return bool(GREET.search(u)) and "老爹" in a and len(a) <= 80


def ok_scold(u, a):
    return bool(SCOLD.search(u)) and any(x in a for x in SELFREF)


def ok_explain(u, a):
    if not EXPLAIN.search(u):
        return False
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    return bool(sents) and max(len(s) for s in sents) >= 35


def parse_md(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        _h, _, body = part.partition("\n")
        if re.search(r"^\s*-\s*status\s*[:：]\s*drop", body, re.M):
            continue
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        msgs = []
        for i in range(1, len(segs) - 1, 2):
            title, text = segs[i].strip(), segs[i + 1].strip()
            if not text:
                continue
            role = "assistant" if "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if len(msgs) >= 2 and msgs[-1]["role"] == "assistant" and msgs[0]["role"] == "user":
            out.append(msgs)
    return out


rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        rows += [{"messages": r["messages"],
                  "source": str(r.get("source", "")).split(":")[0]}
                 for r in (json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip())]

if os.path.isdir(MAT):
    for f in sorted(os.listdir(MAT)):
        if not f.endswith(".md") or f.endswith(("_改名块头前.md", "_压缩前.md")):
            continue
        for msgs in parse_md(os.path.join(MAT, f)):
            rows.append({"messages": msgs, "source": "mat_" + f.replace(".md", "")})

print("候选池 %d 条" % len(rows))

buckets = {"greet": [], "scold": [], "explain": []}
seen = set()
for r in rows:
    us = [m for m in r["messages"] if m.get("role") == "user"]
    as_ = [m for m in r["messages"] if m.get("role") == "assistant"]
    if not us or not as_:
        continue
    u = us[-1].get("content") or ""
    a = as_[-1].get("content") or ""
    if BADCALL.search(a):
        continue
    key = (u.strip()[:40], a.strip()[:40])
    if key in seen:
        continue
    for name, fn_ in (("greet", ok_greet), ("scold", ok_scold), ("explain", ok_explain)):
        if fn_(u, a):
            seen.add(key)
            buckets[name].append({"messages": [{"role": "user", "content": u},
                                               {"role": "assistant", "content": a}],
                                  "source": "patch_" + name, "weight": 1.0})
            break

W = {"greet": 3.0, "scold": 1.5, "explain": 1.0}   # 缺口越大权重越高
allp = []
for name, lst in buckets.items():
    for x in lst:
        x["weight"] = W[name]
        allp.append(x)
    print("  %-8s %4d 条（权重 %.1f）" % (name, len(lst), W[name]))

os.makedirs(OUT, exist_ok=True)
with io.open(os.path.join(OUT, "patch.jsonl"), "w", encoding="utf-8") as f:
    for x in allp:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("\n合计 %d 条 → %s" % (len(allp), os.path.join(OUT, "patch.jsonl")))
print("Σw = %.0f" % sum(x["weight"] for x in allp))
