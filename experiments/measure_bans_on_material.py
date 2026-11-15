# -*- coding: utf-8 -*-
"""量：把老爹的禁令套到素材上，会命中多少条。先量再决定丢还是改。"""
from __future__ import annotations

import collections
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
from backend.text_scrub import has_dash, scrub  # noqa: E402

P = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10", "sft_persona_v9t10_train.jsonl")
bans = json.load(io.open(os.path.join(ROOT, "config", "style_bans.json"), encoding="utf-8"))
PATTERNS = []
for g, ps in (bans.get("groups") or {}).items():
    for p in ps:
        try:
            PATTERNS.append((g, re.compile(p)))
        except re.error:
            pass
# 2026-11-14 追加的硬禁令（不在 style_bans 里的）
EXTRA = [
    ("助理腔", re.compile(r"我理解你的意思|还需要我做什么|还有什么可以帮|随时待命|很高兴为您|为您服务")),
    ("汇报式开头", re.compile(r"^(好的|收到|明白了|了解)[，,。]")),
    ("总结对方", re.compile(r"你(的意思|说的是|说的就是)[，,].{0,20}[，,](所以|也就是说)")),
    ("一句三事", re.compile(r"[^。！？]{0,20}。.{0,10}[^。！？]{0,20}。.{0,10}[^。！？]{0,20}。.{0,10}")),
]

n = 0
hit_rows = 0
by = collections.Counter()
dash_rows = 0
for ln in io.open(P, encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    r = json.loads(ln)
    n += 1
    m = [x for x in (r.get("messages") or []) if isinstance(x, dict)]
    ans = "\n".join(str(x.get("content") or "") for x in m
                    if x.get("role") == "assistant")
    if not ans.strip():
        continue
    hit = False
    if has_dash(ans):
        dash_rows += 1
    for g, pat in PATTERNS:
        if g == "破折号（硬禁）":
            continue
        mm = pat.search(ans)
        if mm:
            by[g] += 1
            hit = True
    for g, pat in EXTRA:
        if g == "一句三事":
            continue
        mm = pat.search(ans)
        if mm:
            by[g] += 1
            hit = True
    if hit:
        hit_rows += 1

print("样本 %d" % n)
print("含破折号（可**修**，不必丢）：%d 条（%.1f%%）" % (dash_rows, 100 * dash_rows / n))
print("命中其它禁令（需决策丢/改）：%d 条（%.1f%%）" % (hit_rows, 100 * hit_rows / n))
print("\n分组命中：")
for g, c in by.most_common():
    print("   %-24s %5d 条（%.1f%%）" % (g, c, 100 * c / n))
