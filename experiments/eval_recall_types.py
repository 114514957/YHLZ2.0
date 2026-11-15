# -*- coding: utf-8 -*-
"""实验：放宽注入类型（加 fact/knowledge/context）+ 语义召回，看召回能到多少。

对比四组：
  A 默认类型(pref/event/decision) + 字符串 3-gram
  B 默认类型 + 语义
  C 全类型 + 语义
  D 全类型 + 语义 + 相对间隔（top1-top2）
"""
from __future__ import annotations

import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from backend.memory_recall_v2 import INJECT_TYPES, load_pool, recall_strict  # noqa: E402
from backend.vector_memory import embed_cls  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
CASES = os.path.join(ROOT, "data", "eval", "memory_recall.jsonl")
cases = [json.loads(x) for x in io.open(CASES, encoding="utf-8") if x.strip()]

WIDE = ("preference", "event", "decision", "fact", "knowledge", "context")


def prep(types):
    pool = load_pool(DB, types=types)
    t0 = time.time()
    P = np.asarray(embed_cls([it["text"] for it in pool]), dtype=np.float32)
    P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
    return pool, P, time.time() - t0


def eval_semantic(pool, P, Q, th: float, margin: float = 0.0) -> dict:
    S = Q @ P.T
    hit = miss = fp = tn = wrong = 0
    for i, c in enumerate(cases):
        order = np.argsort(-S[i])[:3]
        cand = [(pool[j]["id"], float(S[i][j])) for j in order]
        if margin > 0 and len(cand) >= 2:
            cand = [cand[0]] if (cand[0][1] - cand[1][1]) >= margin else cand[:1]
        ids = [cid for cid, sc in cand if sc >= th]
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
            else:
                miss += 1
            if ids and not any(x in ids for x in c["expect_ids"]):
                wrong += 1
        else:
            fp += 1 if ids else 0
            tn += 0 if ids else 1
    returned = hit + wrong + fp
    return {"hit": hit, "n_hit": hit + miss, "fp": fp, "n_no": fp + tn,
            "prec": (hit / returned) if returned else 1.0}


print("=== 准备 ===")
poolA, PA, tA = prep(INJECT_TYPES)
print("  A/B 池（默认类型）：%d 条，嵌入 %.1f 秒" % (len(poolA), tA))
poolC, PC, tC = prep(WIDE)
print("  C/D 池（全类型）  ：%d 条，嵌入 %.1f 秒" % (len(poolC), tC))

Q = np.asarray(embed_cls([c["q"] for c in cases]), dtype=np.float32)
Q /= np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9

# A：字符串
hit = sum(1 for c in cases if c["should_hit"] and any(
    i in [h["id"] for h in recall_strict(c["q"], pool=poolA, limit=3)] for i in c["expect_ids"]))
fpA = sum(1 for c in cases if not c["should_hit"] and recall_strict(c["q"], pool=poolA, limit=3))
print("\n%-34s %-14s %-12s" % ("方案", "命中(召回)", "误报"))
print("-" * 62)
print("%-34s %2d/%-2d %5.0f%%   %2d/%-2d"
      % ("A 默认类型 + 字符串3gram", hit, 25, 100 * hit / 25, fpA, 15))

best = None
for label, pool, P in (("B 默认类型 + 语义", poolA, PA), ("C 全类型 + 语义", poolC, PC)):
    rows = []
    for th in (0.40, 0.45, 0.50, 0.55):
        r = eval_semantic(pool, P, Q, th)
        rows.append((r["hit"], th, r["fp"]))
        print("%-34s %2d/%-2d %5.0f%%   %2d/%-2d"
              % ("%s(th=%.2f)" % (label, th), r["hit"], r["n_hit"],
                 100 * r["hit"] / r["n_hit"], r["fp"], r["n_no"]))
        if best is None or (r["hit"] - 2 * r["fp"]) > best[0]:
            best = (r["hit"] - 2 * r["fp"], label, th, r)
print("\n最佳：%s th=%.2f → 命中 %d/25、误报 %d/15"
      % (best[1], best[2], best[3]["hit"], best[3]["fp"]))
