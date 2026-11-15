# -*- coding: utf-8 -*-
"""看 v9t10 样本的消息角色结构（我上一版过滤把它全丢了，先查清）。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10", "sft_persona_v9t10_train.jsonl")

first_role = Counter()
last_role = Counter()
n = 0
samples = []
for ln in io.open(P, encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    r = json.loads(ln)
    m = [x for x in (r.get("messages") or []) if isinstance(x, dict)]
    if not m:
        continue
    n += 1
    first_role[m[0].get("role")] += 1
    last_role[m[-1].get("role")] += 1
    if len(samples) < 3:
        samples.append(([x.get("role") for x in m], str(m[0].get("content"))[:70]))

print("样本 %d" % n)
print("首条角色分布：%s" % dict(first_role))
print("末条角色分布：%s" % dict(last_role))
for roles, head in samples:
    print("  %s ← %s" % (roles, head.replace("\n", " ")))
