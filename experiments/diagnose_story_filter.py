# -*- coding: utf-8 -*-
"""诊断：559 个老爹口述故事块，倒在哪一层过滤。"""
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
named = re.compile(r"^故事-[^\d｜\s][^｜]*?-\d+｜")
early = re.compile(r"^故事-[1-5]｜")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|大语言模型)")

stats = Counter()
samples = {}
for dirpath, dirs, files in os.walk(MAT):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if not f.endswith(".md"):
            continue
        p = os.path.join(dirpath, f)
        md = io.open(p, encoding="utf-8", errors="replace").read()
        for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
            head, _, body = part.partition("\n")
            head = head.strip()
            if not (named.match(head) or early.match(head)):
                continue
            stats["总块"] += 1
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
            if len(msgs) < 2:
                stats["消息不足"] += 1
                samples.setdefault("消息不足", head)
                continue
            if msgs[0]["role"] != "user":
                stats["首条不是user(旁白开头?)"] += 1
                samples.setdefault("首条不是user", head)
                continue
            if msgs[-1]["role"] != "assistant":
                stats["末条不是assistant"] += 1
                samples.setdefault("末条不是assistant", head)
                continue
            if BADCALL.search(msgs[-1]["content"]):
                stats["被客服腔过滤"] += 1
                samples.setdefault("客服腔", head)
                continue
            stats["可用"] += 1

print("老爹口述故事块诊断：")
for k, v in stats.items():
    print("   %-22s %4d   %s" % (k, v, samples.get(k, "")[:40]))
