# -*- coding: utf-8 -*-
"""查这些口头禅在训练数据里出现多少次（决定要不要洗数据）。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

bans = json.load(io.open(os.path.join(ROOT, "config", "style_bans.json"),
                         encoding="utf-8"))
pats = []
for g, ps in (bans.get("groups") or {}).items():
    for p in ps:
        try:
            pats.append((g, p, re.compile(p)))
        except re.error:
            pass

TRAINS = [
    "dist/retrain_pkg_gemma_v11/sft_persona_v11_train.jsonl",
    "dist/retrain_pkg_gemma_v9t10/sft_persona_v9t10_train.jsonl",
    "dist/retrain_pkg_gemma_v10u/sft_persona_v10u_train.jsonl",
]

for rel in TRAINS:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        print("缺 %s" % rel)
        continue
    rows = 0
    hit_rows = 0
    by_group = Counter()
    examples = {}
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        rows += 1
        msgs = r.get("messages") or []
        txt = "\n".join(str(m.get("content") or "") for m in msgs
                        if isinstance(m, dict) and m.get("role") == "assistant")
        hit = False
        for g, raw, pat in pats:
            m = pat.search(txt)
            if m:
                by_group[g] += 1
                hit = True
                examples.setdefault(g, []).append(m.group(0))
        if hit:
            hit_rows += 1
    print("\n=== %s ===" % os.path.basename(p))
    print("  样本 %d 条｜含拐杖词的 %d 条（%.1f%%）"
          % (rows, hit_rows, 100 * hit_rows / rows if rows else 0))
    for g, n in by_group.most_common():
        top = Counter(examples.get(g, [])).most_common(3)
        print("   %-26s %4d 次｜%s" % (g, n, "、".join("「%s」×%d" % (t[:12], c)
                                                     for t, c in top)))
