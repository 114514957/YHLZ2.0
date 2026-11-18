# -*- coding: utf-8 -*-
"""召回评测跑器：拿 data/eval/memory_recall.jsonl 跑生产召回路径，出精确率/命中率。

为什么要它（台账 1236 §6.4 步2/步4 + 1174 D8）：
  评测集 45 条早在 11-15 就建好了，但一直没有跑器，所以"精确率≥80%""有效命中≥60%"
  这两条验收从来没有数字。这个脚本走**同一条生产路径**：
      pool = memory_recall_v2.load_pool(memstore.db)      # her+owner 才进池
      hits = memory_recall_v2.recall_strict(q, pool=...)  # 3-gram≥2
  不另写一套规则，避免"测的和跑的不是一个东西"。

指标口径：
  · 命中（recall）   = 该命中的题里，命中任一 expect_id 的比例    目标 ≥60%
  · 精确率          = 返回条目中 id ∈ expect_ids 的比例          目标 ≥80%
  · 误召回          = 不该命中的题里，返回了任何条目的比例        越低越好

用法：
    python tools\\recall_eval.py            # 跑全量 45 条
    python tools\\recall_eval.py --json     # 机器可读
    python tools\\recall_eval.py --misses   # 只列没命中的
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
EVAL = os.path.join(ROOT, "data", "eval", "memory_recall.jsonl")

TARGET_PRECISION = 0.80
TARGET_RECALL = 0.60


def load_cases() -> list[dict]:
    return [json.loads(x) for x in io.open(EVAL, encoding="utf-8") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3, help="每条召回条数上限")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--misses", action="store_true", help="只打印未命中/误召回")
    ap.add_argument("--sim", type=float, default=None,
                    help="覆盖相似度门槛 SIM_MIN（默认 0.45），用于扫阈值")
    ap.add_argument("--mode", choices=("semantic", "strict"), default="semantic",
                    help="semantic=生产路径（默认）；strict=3-gram 字面路径对照")
    a = ap.parse_args()

    from backend.memory_recall_v2 import load_pool, recall_strict

    pool = load_pool(DB)
    cases = load_cases()

    idx = None
    if a.sim is not None:
        import backend.memory_recall_semantic as _ms

        _ms.SIM_MIN = float(a.sim)
        print("（覆盖 SIM_MIN=%s）" % a.sim)
    if a.mode == "semantic":
        from backend.memory_recall_semantic import (SemanticIndex, default_paths)

        _db, _vec = default_paths()
        idx = SemanticIndex(_vec)
        if not idx.load(_db):
            idx.build(_db)
        _pool_note = len(pool)
    else:
        _pool_note = len(pool)

    rows = []
    total_returned = 0
    total_correct = 0
    hit_n = 0
    should_n = 0
    fp_n = 0
    none_n = 0

    for c in cases:
        q = str(c.get("q") or "")
        expect = set(map(str, c.get("expect_ids") or []))
        should = bool(c.get("should_hit"))
        if a.mode == "semantic":
            from backend.memory_recall_semantic import default_paths, semantic_recall

            hits = semantic_recall(q, index=idx, db_path=default_paths()[0],
                                   limit=a.limit)
        else:
            hits = recall_strict(q, pool=pool, limit=a.limit)
        ids = [str(h.get("id")) for h in hits]
        got = [i for i in ids if i in expect]
        total_returned += len(ids)
        total_correct += len(got)
        if should:
            should_n += 1
            ok = bool(got)
            hit_n += 1 if ok else 0
        else:
            none_n += 1
            ok = not ids
            fp_n += 1 if ids else 0
        rows.append({"id": c.get("id"), "cat": c.get("cat"), "q": q,
                     "should_hit": should, "expect": sorted(expect),
                     "got": ids, "matched": got, "ok": ok})

    precision = (total_correct / total_returned) if total_returned else 1.0
    recall = (hit_n / should_n) if should_n else 0.0
    fp_rate = (fp_n / none_n) if none_n else 0.0

    by_cat = collections.defaultdict(lambda: {"n": 0, "ok": 0})
    for r in rows:
        b = by_cat[r["cat"] or "-"]
        b["n"] += 1
        b["ok"] += 1 if r["ok"] else 0

    # 2026-11-18：把最近一次结果写盘，供工作台「运行态」卡读取
    try:
        _out = os.path.join(ROOT, "cache", "eval", "recall_last.json")
        os.makedirs(os.path.dirname(_out), exist_ok=True)
        with io.open(_out, "w", encoding="utf-8") as _f:
            json.dump({"at": int(__import__("time").time()),
                       "mode": a.mode, "limit": a.limit,
                       "precision": round(precision, 3),
                       "recall": round(recall, 3),
                       "fp_rate": round(fp_rate, 3),
                       "pool": len(pool),
                       "pass_precision": precision >= TARGET_PRECISION,
                       "pass_recall": recall >= TARGET_RECALL},
                      _f, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass

    if a.json:
        print(json.dumps({"precision": round(precision, 3),
                          "recall": round(recall, 3),
                          "fp_rate": round(fp_rate, 3),
                          "targets": {"precision": TARGET_PRECISION,
                                      "recall": TARGET_RECALL},
                          "pass_precision": precision >= TARGET_PRECISION,
                          "pass_recall": recall >= TARGET_RECALL,
                          "counts": {"cases": len(cases), "should_hit": should_n,
                                     "returned": total_returned,
                                     "correct": total_correct},
                          "mode": a.mode, "pool": len(pool), "rows": rows},
                         ensure_ascii=False, indent=1))
    else:
        print("模式 %s｜池子 %d 条｜题目 %d 条（该命中 %d / 不该命中 %d）"
              % (a.mode, len(pool), len(cases), should_n, none_n))
        print("精确率 %.1f%%（目标 ≥%.0f%%）→ %s"
              % (precision * 100, TARGET_PRECISION * 100,
                 "PASS" if precision >= TARGET_PRECISION else "FAIL"))
        print("命中率 %.1f%%（目标 ≥%.0f%%）→ %s"
              % (recall * 100, TARGET_RECALL * 100,
                 "PASS" if recall >= TARGET_RECALL else "FAIL"))
        print("误召回率 %.1f%%（不该命中却命中）" % (fp_rate * 100))
        print("\n分类：")
        for k, v in sorted(by_cat.items()):
            print("  %-8s %d/%d" % (k, v["ok"], v["n"]))
        if a.misses:
            print("\n未过/误召回：")
            for r in rows:
                if not r["ok"]:
                    print("  %-5s %-6s %s" % (r["id"], r["cat"],
                                              r["q"][:40]))
                    print("        want=%s got=%s" % (r["expect"][:2], r["got"]))

    ok = precision >= TARGET_PRECISION and recall >= TARGET_RECALL
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
