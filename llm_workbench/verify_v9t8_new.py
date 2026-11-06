# -*- coding: utf-8 -*-
"""核对：v9t8 里「素材新增」到底是不是真的没进过包。"""
from __future__ import annotations

import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
V7 = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
V8 = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")


def read(p):
    return [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]


v7 = read(os.path.join(V7, "sft_persona_v9t7_train.jsonl")) + \
     read(os.path.join(V7, "sft_persona_v9t7_val.jsonl"))
v8 = read(os.path.join(V8, "sft_persona_v9t8_train.jsonl")) + \
     read(os.path.join(V8, "sft_persona_v9t8_val.jsonl"))
print("v9t7 %d 条 | v9t8 %d 条" % (len(v7), len(v8)))

v7a = set()
for r in v7:
    for m in r["messages"]:
        if m["role"] == "assistant":
            v7a.add(m["content"].strip())

new = [r for r in v8 if str(r.get("source", "")).startswith("material_full")]
print("material_full 标记 %d 条" % len(new))

# 随机抽 10 条，看答案在 v9t7 里有没有（完全相等 or 前 30 字相等）
random.seed(3)
hit_eq = hit_prefix = none = 0
for r in random.sample(new, min(10, len(new))):
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1].strip()
    if a in v7a:
        hit_eq += 1
        tag = "完整重复"
    elif any(x[:30] == a[:30] for x in v7a):
        hit_prefix += 1
        tag = "前缀重复"
    else:
        none += 1
        tag = "确实新"
    print("  [%s] %s" % (tag, a[:52]))

# 全量统计（精确相等）
in_v7 = sum(1 for r in new
            if [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1].strip() in v7a)
print("\n全量：material_full 里答案与 v9t7 完全相同的 %d / %d" % (in_v7, len(new)))
