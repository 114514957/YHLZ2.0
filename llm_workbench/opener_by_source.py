# -*- coding: utf-8 -*-
"""按来源统计开头两字，定位「记得」到底从哪来。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\dist\retrain_pkg_gemma_v9t7"
rows = []
for fn in ("sft_persona_v9t6t_train.jsonl", "sft_persona_v9t6t_val.jsonl"):
    with io.open(os.path.join(D, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

per: dict[str, Counter] = {}
for r in rows:
    msgs = r.get("messages") or []
    asst = [m["content"] for m in msgs if m.get("role") == "assistant"]
    if not asst:
        continue
    src = str(r.get("source", "")).split(":")[0] or "?"
    per.setdefault(src, Counter())[asst[-1].strip()[:2]] += 1

print("source | top opener | count | source total")
for src, c in sorted(per.items(), key=lambda x: -sum(x[1].values())):
    top, cnt = c.most_common(1)[0]
    print("%-14s | %-6s | %4d / %4d" % (src, top, cnt, sum(c.values())))
