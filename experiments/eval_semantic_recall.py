# -*- coding: utf-8 -*-
"""语义召回评测：用 512 维嵌入做 cosine top-k，和字符串召回对比。

目的：回答"记忆召回的根问题是精度，还是根本没有语义能力"。
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

from backend.memory_recall_v2 import load_pool  # noqa: E402
from backend.vector_memory import embed_cls  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
CASES = os.path.join(ROOT, "data", "eval", "memory_recall.jsonl")

cases = [json.loads(x) for x in io.open(CASES, encoding="utf-8") if x.strip()]
pool = load_pool(DB)
print("候选池 %d 条｜评测集 %d 条" % (len(pool), len(cases)))

t0 = time.time()
P = np.asarray(embed_cls([it["text"] for it in pool]), dtype=np.float32)
P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
Q = np.asarray(embed_cls([c["q"] for c in cases]), dtype=np.float32)
Q /= np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9
print("嵌入完成：池 %s｜问句 %s｜耗时 %.1f 秒" % (P.shape, Q.shape, time.time() - t0))

S = Q @ P.T  # (n_cases, n_pool)


def evaluate(th: float, limit: int = 3) -> dict:
    hit = miss = fp = tn = wrong = 0
    for i, c in enumerate(cases):
        order = np.argsort(-S[i])[:limit]
        got = [(pool[j]["id"], float(S[i][j])) for j in order if S[i][j] >= th]
        ids = [g[0] for g in got]
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
            else:
                miss += 1
            if ids and not any(x in ids for x in c["expect_ids"]):
                wrong += 1
        else:
            if ids:
                fp += 1
            else:
                tn += 1
    returned = hit + wrong + fp
    return {"th": th, "hit": hit, "n_hit": hit + miss, "fp": fp, "n_no": fp + tn,
            "prec": (hit / returned) if returned else 1.0}


print("\n阈值    命中(召回)      误报        精确率")
print("-" * 56)
best = None
for th in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65):
    r = evaluate(th)
    print("%.2f    %2d/%-2d %5.0f%%    %2d/%-2d %4.0f%%    %5.0f%%"
          % (th, r["hit"], r["n_hit"], 100 * r["hit"] / max(1, r["n_hit"]),
             r["fp"], r["n_no"], 100 * r["fp"] / max(1, r["n_no"]), 100 * r["prec"]))
    score = r["hit"] - 2 * r["fp"]
    if best is None or score > best[0]:
        best = (score, th)

print("\n参考：字符串版命中 3/25 (12%)、误报 0/15")
print("建议阈值：%.2f" % best[1])

print("\n=== 阈值 %.2f 下的逐题（应命中的前 12 条）===" % best[1])
shown = 0
for i, c in enumerate(cases):
    if not c["should_hit"] or shown >= 12:
        continue
    order = np.argsort(-S[i])[:3]
    cand = [(pool[j]["id"], float(S[i][j])) for j in order]
    ok = any(cid in c["expect_ids"] for cid, _s in cand if _s >= best[1])
    shown += 1
    print("%s %-4s %s" % ("✅" if ok else "❌", c["id"], c["q"][:34]))
    for cid, sc in cand:
        mark = "★" if cid in c["expect_ids"] else " "
        print("      %s %.3f %s" % (mark, sc, pool[[p["id"] for p in pool].index(cid)]["text"][:56]))
