# -*- coding: utf-8 -*-
"""每个来源抽 2 条，看它到底在教什么口吻。"""
from __future__ import annotations

import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\dist\retrain_pkg_gemma_v9t7"
random.seed(7)

rows = []
for fn in ("sft_persona_v9t6t_train.jsonl", "sft_persona_v9t6t_val.jsonl"):
    with io.open(os.path.join(D, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

by: dict[str, list] = {}
for r in rows:
    src = str(r.get("source", "")).split(":")[0] or "?"
    by.setdefault(src, []).append(r)

for src in sorted(by, key=lambda s: -len(by[s])):
    print("=" * 66)
    print("%s（%d 条）" % (src, len(by[src])))
    for r in random.sample(by[src], min(2, len(by[src]))):
        msgs = r["messages"]
        q = next((m["content"] for m in msgs if m["role"] == "user"), "")
        a = [m["content"] for m in msgs if m["role"] == "assistant"][-1]
        print("   问：%s" % q.replace("\n", " ")[:50])
        print("   答：%s" % a.replace("\n", " ")[:70])
