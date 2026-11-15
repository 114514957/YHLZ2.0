# -*- coding: utf-8 -*-
"""收紧版：只找**真骂人/真荤话**，看元亨回了什么。顺带统计「道德挡板」出现率。"""
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
BOT = "3655185302"

DIRTY = re.compile(r"(傻逼|煞笔|沙比|妈的|你妈|操你|草你|日你|去死|智障|脑残|狗东西|滚蛋|"
                   r"开黄腔|黄的|荤段|上床|约炮|裸照|做爱)")
# 她的「道德挡板」措辞——新方向下这些是反教材
MORAL = re.compile(r"(保持礼貌|注意言辞|请文明|别这样|不合适|不聊这个|换个话题|"
                   r"我不能|抱歉|理解你的心情)")

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
                pairs.append((prev, t))
            prev = None
        else:
            prev = t

moral = [p for p in pairs if MORAL.search(p[1])]
print("群友真骂人/真荤话 → 元亨接话：%d 对" % len(pairs))
print("其中她用了「道德挡板」：%d 对（%.0f%%）" % (len(moral), 100 * len(moral) / max(1, len(pairs))))
print("\n全部样例：")
for q, a in pairs[:30]:
    tag = "⚠挡板" if MORAL.search(a) else "✓"
    print("  %s 群友：%s" % (tag, q[:44]))
    print("      元亨：%s" % a[:80])
