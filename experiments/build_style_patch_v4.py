# -*- coding: utf-8 -*-
"""补丁 v4：把多轮故事块压成「首问 + 最长那段答」的单轮对，长度可控。

上一版的教训：max_seq_len 384 下 162/363 条被判超长丢弃（正是最需要的长故事块）。
本版在**造数据时**就控制长度，而不是靠训练器截断/丢弃。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
SUBS = ["_草稿", "_归档", "_修订", "_原素材", "_待定"]
V3 = os.path.join(YH, "dist", "style_patch_v3", "patch.jsonl")
OUT = os.path.join(YH, "dist", "style_patch_v4")
MAX_A = 900          # 答案最长字符数（约 500 token，够放一段长句又不至于撑爆）
MAX_U = 120


def parse(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        if "示例" in head:
            continue
        if re.search(r"^\s*-\s*status\s*[:：]\s*drop", body, re.M):
            continue
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        msgs = []
        for i in range(1, len(segs) - 1, 2):
            title, text = segs[i].strip(), segs[i + 1].strip()
            if not text:
                continue
            role = "assistant" if "元亨" in text or "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if msgs and msgs[0]["role"] == "user":
            out.append({"head": head.strip(), "msgs": msgs})
    return out


items = []
seen = set()

# ① v3 里已有的短样本（非 story）直接留
for x in (json.loads(s) for s in io.open(V3, encoding="utf-8") if s.strip()):
    if x["source"] == "patch_story_long":
        continue
    u = x["messages"][0]["content"]
    a = x["messages"][-1]["content"]
    if len(a) > MAX_A:
        continue
    items.append({"messages": [{"role": "user", "content": u[:MAX_U]},
                               {"role": "assistant", "content": a}],
                  "source": x["source"], "weight": x["weight"]})
    seen.add((u[:40], a[:40]))

# ② 故事块 → 单轮（首问 + 最长的那段元亨发言）
added = 0
for sub in SUBS:
    d = os.path.join(MAT, sub)
    if not os.path.isdir(d):
        continue
    for p in glob.glob(os.path.join(d, "**", "*.md"), recursive=True):
        for b in parse(p):
            if not b["head"].startswith("故事"):
                continue
            users = [m["content"] for m in b["msgs"] if m["role"] == "user"]
            asst = [m["content"] for m in b["msgs"] if m["role"] == "assistant"
                    and len(m["content"]) >= 80]
            if not users or not asst:
                continue
            a = max(asst, key=len)
            sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
            if not sents or max(len(s) for s in sents) < 35:
                continue
            if len(a) > MAX_A:
                a = a[:MAX_A].rsplit("。", 1)[0] + "。"
            u = users[0][:MAX_U]
            key = (u[:40], a[:40])
            if key in seen:
                continue
            seen.add(key)
            items.append({"messages": [{"role": "user", "content": u},
                                       {"role": "assistant", "content": a}],
                          "source": "patch_story1", "weight": 1.5})
            added += 1

os.makedirs(OUT, exist_ok=True)
with io.open(os.path.join(OUT, "patch.jsonl"), "w", encoding="utf-8") as f:
    for x in items:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")

print("补丁 v4：%d 条｜Σw %.0f｜故事单轮新增 %d"
      % (len(items), sum(x["weight"] for x in items), added))
for k, v in Counter(x["source"] for x in items).most_common():
    print("   %-18s %3d" % (k, v))
lens = sorted(len(x["messages"][-1]["content"]) for x in items)
print("答案长度：中位 %d｜p90 %d｜最长 %d"
      % (lens[len(lens) // 2], lens[int(0.9 * len(lens))], lens[-1]))
