# -*- coding: utf-8 -*-
"""查重叠：docs/素材 里的句子，有多少已经在 v9t10 包里（按用户话前 30 字比对）。"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
SKIP = {"素材库.md", "素材清单_v2_20261018.md", "README_规范.md",
        "长对话生成提示词_v0_20261008.md"}


def parse_file(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        st = re.search(r"^\s*-\s*status\s*[:：]\s*(.*)$", body, re.M)
        if st and st.group(1).strip() == "drop":
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


pack_first = set()
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            us = [m["content"] for m in r["messages"] if m.get("role") == "user"]
            if us:
                pack_first.add(us[0].strip()[:30])

files = sorted(f for f in os.listdir(MAT)
               if f.endswith(".md") and f not in SKIP
               and not f.endswith(("_改名块头前.md", "_压缩前.md", "_补称呼前.md")))
tot = dup = 0
per = {}
for f in files:
    ms = parse_file(os.path.join(MAT, f))
    d = sum(1 for m in ms if m[0]["content"].strip()[:30] in pack_first)
    per[f] = (len(ms), d)
    tot += len(ms)
    dup += d
for f, (n, d) in per.items():
    if n:
        print("%-24s %4d 条｜前30字已在包里 %4d（%.0f%%）"
              % (f, n, d, 100 * d / n))
print("\n合计 %d｜语义重叠 %d（%.0f%%）｜真正新增约 %d"
      % (tot, dup, 100 * dup / max(1, tot), tot - dup))
