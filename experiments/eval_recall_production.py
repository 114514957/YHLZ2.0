# -*- coding: utf-8 -*-
"""用**生产模块**（SemanticIndex.load + search）跑评测集，拿到上线后的真实数字。

对比三档：旧字符串 / 新语义 / 语义+闸门（生产路径）。
45 条（25 应命中 + 20 应无命中，其中 5 条是长句闲聊的"难负样本"）。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.memory_recall_semantic import (SemanticIndex, default_paths,
                                            gate_allows)
from backend.memory_recall_v2 import load_pool, recall_strict
from backend.target_memory import TargetMemoryService  # noqa: E402

db, vec = default_paths(ROOT)
cases = [json.loads(x) for x in
         io.open(os.path.join(ROOT, "data", "eval", "memory_recall.jsonl"),
                 encoding="utf-8") if x.strip()]
svc = TargetMemoryService(db_path=str(db))

idx = SemanticIndex(vec)
ok = idx.load(db)
print("索引载入：%s｜条目 %d" % ("✅" if ok else "❌", len(idx._ids)))

pool_old = load_pool(db)              # 旧类型集合
pool_wide = load_pool(db, types=("preference", "event", "decision",
                                 "fact", "knowledge", "context"))


def old_string(q):
    return [h.get("id") for h in svc.contextual_recall(q, limit=3)]


def strict_wide(q):
    return [h["id"] for h in recall_strict(q, pool=pool_wide, limit=2)]


def semantic_gated(q):
    return [h["id"] for h in idx.search(q)]


def calib(q):
    """阈值校准：看 top1 相似度与闸门原因（不返回结果）"""
    okk, why = gate_allows(q)
    if not okk or not len(idx._ids):
        return {"allowed": okk, "why": why, "top": 0.0}
    import numpy as np
    from backend.vector_memory import embed_cls
    v = np.asarray(embed_cls([q]), dtype=np.float32)[0]
    v /= (np.linalg.norm(v) + 1e-9)
    sims = idx._matrix @ v
    order = np.argsort(-sims)[:2]
    return {"allowed": True, "why": why, "top": float(sims[order[0]]),
            "top2": float(sims[order[1]]) if len(order) > 1 else 0.0,
            "id": idx._ids[int(order[0])]}


def report(name, fn):
    hit = miss = fp = tn = 0
    hard_fp = 0
    for c in cases:
        ids = [x for x in fn(c["q"]) if x]
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
            else:
                miss += 1
        else:
            if ids:
                fp += 1
                if c.get("cat") == "hard":
                    hard_fp += 1
            else:
                tn += 1
    n_hit = hit + miss
    n_no = fp + tn
    print("%-22s 命中 %2d/%-2d %5.0f%%   误报 %2d/%-2d %4.0f%%   (难负样本误报 %d/5)"
          % (name, hit, n_hit, 100 * hit / max(1, n_hit), fp, n_no,
             100 * fp / max(1, n_no), hard_fp))
    return {"hit": hit, "n_hit": n_hit, "fp": fp, "n_no": n_no, "hard_fp": hard_fp}


print("\n方案                      命中(召回)          误报")
print("-" * 78)
report("旧 contextual_recall", old_string)
report("字符串 3-gram(宽类型)", strict_wide)
report("语义+闸门（生产）", semantic_gated)

print("\n=== 难负样本（长句闲聊）逐条 ===")
for c in cases:
    if c.get("cat") != "hard":
        continue
    ids = semantic_gated(c["q"])
    cal = calib(c["q"])
    print("%s %-4s %-26s top=%.3f → %s"
          % ("⚠" if ids else "✅", c["id"], c["q"][:26], cal.get("top", 0),
             ids[:2] or "无"))

print("\n=== 应命中的失败项（看还差什么）===")
for c in cases:
    if not c["should_hit"]:
        continue
    ids = semantic_gated(c["q"])
    if not any(x in ids for x in c["expect_ids"]):
        cal = calib(c["q"])
        print("❌ %-4s %-30s why=%-10s top=%.3f top2=%.3f"
              % (c["id"], c["q"][:30], cal.get("why"), cal.get("top", 0),
                 cal.get("top2", 0)))
