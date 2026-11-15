# -*- coding: utf-8 -*-
"""记忆召回评测：新旧两版对比（38 条：25 应命中 + 13 应无命中）。

指标：
  命中率(hit)    —— 应命中的题里，top-3 里出现期望 id 的比例（召回）
  误报率(FP)     —— 应无命中的题里，返回了东西的比例（越低越好）
  精确率(prec)   —— 所有"返回了东西"的题里，确实命中期望 id 的比例
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.memory_recall_v2 import load_pool, recall_strict  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
CASES = os.path.join(ROOT, "data", "eval", "memory_recall.jsonl")

cases = [json.loads(x) for x in io.open(CASES, encoding="utf-8") if x.strip()]
svc = TargetMemoryService(db_path=DB)
pool = load_pool(DB)
print("评测集 %d 条｜v2 候选池 %d 条（active + pref/event/decision + her/owner + 非碎片）"
      % (len(cases), len(pool)))


def run_old(q: str) -> list[str]:
    try:
        return [str(h.get("id")) for h in svc.contextual_recall(q, limit=3)]
    except Exception:  # noqa: BLE001
        return []


def run_new(q: str) -> list[str]:
    return [h["id"] for h in recall_strict(q, pool=pool, limit=3)]


def evaluate(label: str, fn) -> dict:
    hit = miss = fp = tn = 0
    wrong_hits = 0
    details = []
    for c in cases:
        got = fn(c["q"])
        if c["should_hit"]:
            ok = any(i in got for i in c["expect_ids"])
            if ok:
                hit += 1
            else:
                miss += 1
            if got and not ok:
                wrong_hits += 1
            details.append((c["id"], c["should_hit"], ok, got[:2]))
        else:
            if got:
                fp += 1
            else:
                tn += 1
            details.append((c["id"], c["should_hit"], not got, got[:2]))
    n_hit = hit + miss
    n_no = fp + tn
    # 精确率：所有"给出了结果"的题里，命中期望的比例
    returned = hit + wrong_hits + fp
    prec = (hit / returned) if returned else 1.0
    return {"label": label, "hit": hit, "miss": miss, "hit_rate": hit / max(1, n_hit),
            "fp": fp, "tn": tn, "fp_rate": fp / max(1, n_no), "precision": prec,
            "details": details}


old = evaluate("旧 contextual_recall", run_old)
new = evaluate("新 recall_strict(v2)", run_new)

print("\n%-24s %-14s %-14s %-12s" % ("版本", "命中(召回)", "误报率", "精确率"))
print("-" * 68)
for r in (old, new):
    print("%-24s %2d/%-2d %5.0f%%   %2d/%-2d %4.0f%%   %5.0f%%"
          % (r["label"], r["hit"], r["hit"] + r["miss"], 100 * r["hit_rate"],
             r["fp"], r["fp"] + r["tn"], 100 * r["fp_rate"], 100 * r["precision"]))

print("\n=== 逐题（新版本对照）===")
om = {d[0]: d for d in old["details"]}
nm = {d[0]: d for d in new["details"]}
for c in cases:
    o, n = om[c["id"]], nm[c["id"]]
    flag = "✅" if (n[2] and not o[2]) else ("❌" if (o[2] and not n[2]) else "  ")
    print("%s %-4s 应%s｜旧%s 新%s｜%s" % (
        flag, c["id"], "命中" if c["should_hit"] else "无命中",
        "中" if o[2] else "空", "中" if n[2] else "空",
        c["q"][:36]))
