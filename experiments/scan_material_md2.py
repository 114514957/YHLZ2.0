# -*- coding: utf-8 -*-
"""通用解析 docs/素材/*.md：块 = `## 标题`，块内 `### X` 段按「元亨→assistant，其余→user」。

统计各文件能抽出多少条可训练对话（首版，只统计）。
"""
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
SKIP = {"素材库.md", "素材清单_v2_20261018.md", "README_规范.md",
        "长对话生成提示词_v0_20261008.md"}


def parse_file(path: str):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        st = re.search(r"^\s*-\s*status\s*[:：]\s*(.*)$", body, re.M)
        if st and st.group(1).strip() == "drop":
            continue
        # 按 ### 切段
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        msgs = []
        for i in range(1, len(segs) - 1, 2):
            title = segs[i].strip()
            text = segs[i + 1].strip()
            if not text:
                continue
            role = "assistant" if "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:      # 同角色合并
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if len(msgs) < 2 or msgs[-1]["role"] != "assistant" or msgs[0]["role"] != "user":
            continue
        if len(msgs[-1]["content"]) < 2:
            continue
        out.append((head.strip(), msgs))
    return out


seen = set()
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                seen.add(json.dumps([m.get("content") for m in r["messages"]],
                                    ensure_ascii=False))

files = sorted(f for f in os.listdir(MAT)
               if f.endswith(".md") and f not in SKIP
               and not f.endswith(("_改名块头前.md", "_压缩前.md", "_补称呼前.md")))
total = newt = 0
for f in files:
    pairs = parse_file(os.path.join(MAT, f))
    new = 0
    for head, msgs in pairs:
        k = json.dumps([m["content"] for m in msgs], ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            new += 1
    total += len(pairs)
    newt += new
    if pairs:
        print("%-24s 可训 %3d｜去重后 %3d" % (f, len(pairs), new))
print("\n合计可训 %d 条｜去重后新增 **%d** 条" % (total, newt))
