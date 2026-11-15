# -*- coding: utf-8 -*-
"""风格补丁 v3：在 v2 基础上并入「含 ≥35 字长句」的 52 个故事块（子目录里那些）。"""
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
V2 = os.path.join(YH, "dist", "style_patch_v2", "patch.jsonl")
OUT = os.path.join(YH, "dist", "style_patch_v3")
SUBS = ["_草稿", "_归档", "_修订", "_原素材", "_待定"]


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
            role = "assistant" if "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if len(msgs) >= 2 and msgs[-1]["role"] == "assistant" and msgs[0]["role"] == "user":
            out.append({"head": head.strip(), "msgs": msgs})
    return out


base = [json.loads(x) for x in io.open(V2, encoding="utf-8") if x.strip()]
seen = {(x["messages"][0]["content"][:40], x["messages"][-1]["content"][:40]) for x in base}
print("v2 已有 %d 条" % len(base))

added = 0
long_blocks = 0
for sub in SUBS:
    d = os.path.join(MAT, sub)
    if not os.path.isdir(d):
        continue
    for p in glob.glob(os.path.join(d, "**", "*.md"), recursive=True):
        for b in parse(p):
            if not b["head"].startswith("故事"):
                continue
            a_all = "\n".join(m["content"] for m in b["msgs"] if m["role"] == "assistant")
            sents = [s for s in re.split(r"[。！？\n]+", a_all) if s.strip()]
            if not sents or max(len(s) for s in sents) < 35:
                continue
            long_blocks += 1
            u = b["msgs"][0]["content"]
            a = b["msgs"][-1]["content"]
            key = (u[:40], a[:40])
            if key in seen:
                continue
            seen.add(key)
            base.append({"messages": [{"role": "user", "content": u},
                                      {"role": "assistant", "content": a}],
                         "source": "patch_story_long", "weight": 1.5})
            added += 1

os.makedirs(OUT, exist_ok=True)
with io.open(os.path.join(OUT, "patch.jsonl"), "w", encoding="utf-8") as f:
    for x in base:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")

cnt = Counter(x["source"] for x in base)
print("含长句的故事块 %d 个｜新增 %d 条" % (long_blocks, added))
print("补丁 v3 合计 %d 条｜Σw %.0f" % (len(base), sum(x["weight"] for x in base)))
for k, v in cnt.most_common():
    w = sum(x["weight"] for x in base if x["source"] == k)
    print("   %-20s %3d 条｜Σw %5.1f" % (k, v, w))
