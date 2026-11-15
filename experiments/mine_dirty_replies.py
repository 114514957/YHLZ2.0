# -*- coding: utf-8 -*-
"""挖真实数据：群友说了脏话/荤话时，元亨**实际回了什么**。

这是「她接不接得住脏话」唯一的原文证据，不靠我们编。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
EXP = os.path.join(YH, "cache", "qq_export")
OUT = os.path.join(YH, "docs", "研究", "脏话接话原文_20261108.md")
BOT = "3655185302"

DIRTY = re.compile(r"(傻逼|煞笔|沙比|妈的|他妈的|你妈|操你|草你|艹|日你|滚蛋|狗东西|贱|去死|"
                   r"废物|智障|脑残|变态|色|黄|荤|骚|浪|上床|约|脱|裸|胸|屁股|睡觉|亲|抱|"
                   r"哈哈哈哈哈|草|靠|卧槽|我日|尼玛|泥马|屌|屁事|妈的)")

msgs = {}
for p in sorted(glob.glob(os.path.join(EXP, "*.jsonl"))):
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        msgs[(r.get("group_id"), r.get("seq"))] = r

by_group = {}
for (g, s), r in msgs.items():
    by_group.setdefault(g, []).append(r)
for g in by_group:
    by_group[g].sort(key=lambda x: x.get("seq") or 0)

pairs = []
for g, rows in by_group.items():
    prev = None
    for r in rows:
        t = (r.get("text") or "").strip()
        if not t:
            continue
        is_bot = (str(r.get("sender_id")) == BOT
                  or str(r.get("message_id", "")).startswith("bot:"))
        if is_bot:
            if prev and DIRTY.search(prev):
                pairs.append((prev, t, g, r.get("seq")))
            prev = None
        else:
            prev = t

seen, uniq = set(), []
for q, a, g, s in pairs:
    if a[:30] in seen:
        continue
    seen.add(a[:30])
    uniq.append((q, a, g, s))

print("群友带脏/荤 → 元亨接话：原始 %d 对，去重 %d 对" % (len(pairs), len(uniq)))
for q, a, g, s in uniq[:25]:
    print("  群友：%s" % q[:40])
    print("  元亨：%s" % a[:70])
    print()

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 脏话/荤话 接话原文（2026-11-08）\n\n")
    f.write("> 来源 `cache/qq_export/*.jsonl`：群友说脏话/荤话后，元亨的真实回复。**原文未改**。\n")
    f.write("> 共 %d 对（去重）。用途：训练「听得懂低俗、不装傻」的正样本。\n\n" % len(uniq))
    for q, a, g, s in uniq:
        f.write("- 群友：%s\n  - 元亨：%s\n\n" % (q[:120], a[:300]))
print("写出 %s" % OUT)
