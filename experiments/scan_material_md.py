# -*- coding: utf-8 -*-
"""从 docs/素材/*.md 抽 (用户, 元亨) 原文对，统计能进包多少（本步只统计，不写包）。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")

H_USER = re.compile(r"^###\s*(老爹|用户|群友|user)\s*$", re.M)
H_BOT = re.compile(r"^###\s*(元亨|assistant)\s*$", re.M)


def blocks(md: str):
    parts = re.split(r"^##\s+", md, flags=re.M)
    for p in parts[1:]:
        head, _, body = p.partition("\n")
        yield head.strip(), body


def meta(body: str, key: str) -> str:
    m = re.search(r"^\s*-\s*%s\s*[:：]\s*(.*)$" % key, body, re.M)
    return m.group(1).strip() if m else ""


def parse_pair(body: str):
    mu = H_USER.search(body)
    mb = H_BOT.search(body)
    if not mu or not mb or mu.end() > mb.end():
        return None
    u = body[mu.end():mb.start()].strip()
    tail = body[mb.end():]
    # 元亨段到下一个 ### 或块尾
    nxt = re.search(r"^###\s", tail, re.M)
    a = (tail[:nxt.start()] if nxt else tail).strip()
    if not u or not a:
        return None
    return u, a


srcs = sorted(f for f in os.listdir(MAT) if f.endswith(".md")
              and not f.endswith(("_改名块头前.md", "_压缩前.md", "_补称呼前.md"))
              and f not in ("素材库.md", "素材清单_v2_20261018.md",
                            "README_规范.md", "长对话生成提示词_v0_20261008.md"))

# 包内已有内容（去重用）
seen = set()
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                seen.add(json.dumps([m.get("content") for m in r["messages"]],
                                    ensure_ascii=False))

total_new = 0
plan = {}
for f in srcs:
    md = io.open(os.path.join(MAT, f), encoding="utf-8", errors="replace").read()
    keep = new = drop = 0
    for head, body in blocks(md):
        st = meta(body, "status")
        pr = parse_pair(body)
        if not pr:
            continue
        if st == "drop":
            drop += 1
            continue
        u, a = pr
        key = json.dumps([{"role": "user", "content": u},
                          {"role": "assistant", "content": a}]
                         and [u, a], ensure_ascii=False)
        keep += 1
        if key in seen:
            continue
        seen.add(key)
        new += 1
    plan[f] = (keep, new, drop)
    total_new += new
    print("%-26s 块内成对 %3d｜去重后新增 %3d｜drop %d" % (f, keep, new, drop))

print("\n合计可新增 **%d** 条（这些是原文，能直接进包）" % total_new)
