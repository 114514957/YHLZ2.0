# -*- coding: utf-8 -*-
"""统计子目录（_草稿/_归档/_修订）里的故事块：数量、元亨最长段落、长句率。"""
from __future__ import annotations

import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
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
        if len(msgs) >= 2 and msgs[-1]["role"] == "assistant":
            out.append({"head": head.strip(), "msgs": msgs})
    return out


total = 0
story = []
for sub in SUBS:
    d = os.path.join(MAT, sub)
    if not os.path.isdir(d):
        continue
    for p in glob.glob(os.path.join(d, "**", "*.md"), recursive=True):
        blocks = parse(p)
        total += len(blocks)
        for b in blocks:
            story.append({"file": os.path.relpath(p, MAT), "head": b["head"],
                          "msgs": b["msgs"]})

print("子目录共解析 %d 块｜其中故事块 %d 块"
      % (total, sum(1 for s in story if s["head"].startswith("故事"))))

def profile(msgs):
    a = [m for m in msgs if m["role"] == "assistant"]
    txt = "\n".join(m["content"] for m in a)
    sents = [s for s in re.split(r"[。！？\n]+", txt) if s.strip()]
    if not sents:
        return 0, 0, 0
    longest = max(len(s) for s in sents)
    long_ratio = sum(1 for s in sents if len(s) >= 35) / len(sents)
    return longest, long_ratio, len(sents)

rows = []
for s in story:
    if not s["head"].startswith("故事"):
        continue
    longest, ratio, n = profile(s["msgs"])
    rows.append((s["head"], s["file"], longest, ratio, n))

rows.sort(key=lambda x: -x[2])
print("\n最长的 8 块：")
for h, f, longest, ratio, n in rows[:8]:
    print("  %-34s 最长句 %3d 字｜长句率 %.0f%%｜%3d 句｜%s"
          % (h[:34], longest, 100 * ratio, n, f))
print("\n其中「最长句 ≥35」的块：%d / %d"
      % (sum(1 for r in rows if r[2] >= 35), len(rows)))
print("其中「长句率 ≥40%%」的块：%d / %d"
      % (sum(1 for r in rows if r[3] >= 0.4), len(rows)))
