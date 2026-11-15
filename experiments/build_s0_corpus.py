# -*- coding: utf-8 -*-
"""拼一份多样语料（docs/素材 + 台账 + 研究笔记），去掉 markdown 标记，一行一段。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "cache", "s0_corpus.txt")

srcs = []
for root, _d, files in os.walk(os.path.join(YH, "docs", "素材")):
    for f in files:
        if f.endswith(".md") and not f.endswith(("_改名块头前.md", "_压缩前.md")):
            srcs.append(os.path.join(root, f))
for f in ("上下文台账.md",):
    p = os.path.join(YH, "docs", f)
    if os.path.exists(p):
        srcs.append(p)
for root, _d, files in os.walk(os.path.join(YH, "docs", "研究")):
    for f in files:
        if f.endswith(".md"):
            srcs.append(os.path.join(root, f))

lines = []
seen = set()
for p in srcs:
    try:
        txt = io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        continue
    for ln in txt.splitlines():
        ln = re.sub(r"^[#>\-\*\s]+", "", ln).strip()
        ln = re.sub(r"[`*_\[\]()]", "", ln)
        if len(ln) < 20 or len(ln) > 400:
            continue
        if ln in seen:
            continue
        seen.add(ln)
        lines.append(ln)

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("语料 %d 段 → %s（%.1f KB）" % (len(lines), OUT, os.path.getsize(OUT) / 1024))
