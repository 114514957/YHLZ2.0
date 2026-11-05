# -*- coding: utf-8 -*-
"""校验 v9t7 包：行数、三段结构、哈希去重、来源分布。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\dist\retrain_pkg_gemma_v9t7"


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


tr = read(os.path.join(D, "sft_persona_v9t6t_train.jsonl"))
va = read(os.path.join(D, "sft_persona_v9t6t_val.jsonl"))
print("train %d | val %d | 合计 %d" % (len(tr), len(va), len(tr) + len(va)))

bad = [r for r in tr + va if len(r.get("messages") or []) != 3]
print("非三段样本：%d" % len(bad))

h = [r.get("content_hash") for r in tr + va]
print("哈希：%d 条 / 去重后 %d" % (len(h), len(set(h))))

src = {}
for r in tr + va:
    k = str(r.get("source", "")).split(":")[0]
    src[k] = src.get(k, 0) + 1
print("来源分布 Top8：%s" % sorted(src.items(), key=lambda x: -x[1])[:8])

# 补丁有没有整组漏进 val
sup = [r for r in tr + va if str(r.get("source", "")).startswith(("internal_refusal", "qq_short"))]
print("补丁在包里：%d 条（train %d / val %d）"
      % (len(sup),
         sum(1 for r in tr if str(r.get("source", "")).startswith(("internal_refusal", "qq_short"))),
         sum(1 for r in va if str(r.get("source", "")).startswith(("internal_refusal", "qq_short")))))

with io.open(os.path.join(D, "MANIFEST.json"), encoding="utf-8") as f:
    m = json.load(f)
print("MANIFEST:", json.dumps(m["supplement"], ensure_ascii=False))
