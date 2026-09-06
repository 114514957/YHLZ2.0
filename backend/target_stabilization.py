"""Memory stabilization adapter (ledger 0196, batch-2 #1).

Wraps the embodied MemoryStabilizationEngine (compress / prune-candidates /
weight-evaluate / conflict-detect + full audit) over the TARGET L2 store.

Design red lines:
- READ-ONLY audit by default: the engine only *proposes*; nothing is written
  here. Execution stays explicit (owner-approved) — matches the engine's own
  "prune candidates only, execute requires explicit call" principle and our
  approval culture.
- Records adapt: L2 item -> {id, trigger, value, confidence, timestamp}.
"""
from __future__ import annotations

import time
from typing import Optional

_PROJECT = None


def _engine(config: Optional[dict] = None):
    from backend.embodied.companion.memory_stabilization import (
        MemoryStabilizationEngine,
    )

    return MemoryStabilizationEngine(config=config or {}, enabled=True)


def _records_from_l2(memory) -> list[dict]:
    """Read active L2 items into stabilization record dicts."""
    import sqlite3

    con = sqlite3.connect(str(memory.db_path))
    rows = con.execute(
        "SELECT id, type, importance, belief, summary, keywords, created_at "
        "FROM l2_items WHERE status='active'"
    ).fetchall()
    con.close()
    records = []
    for iid, typ, imp, belief, summary, kw, created in rows:
        trigger = str(kw or typ or "")[:12] or str(typ)
        records.append({
            "id": iid,
            "trigger": trigger,
            "value": max(0.05, min(1.0, (int(imp or 0) + float(belief or 0.5)) / 10.0)),
            "confidence": round(float(belief or 0.5), 3),
            "timestamp": float(created or time.time()),
            "_summary": str(summary)[:140],
        })
    return records


def stabilize_report(memory, limit_detail: int = 40) -> dict:
    """Run the stabilization engine over active L2 and summarize its proposals."""
    eng = _engine()
    records = _records_from_l2(memory)
    if not records:
        return {"total": 0}
    # gather extra fields the engine ignores but the report wants
    meta = {r["id"]: r.get("_summary", "") for r in records}
    confirmed = {r["id"] for r in records if r.get("value", 0) >= 0.8}
    rep = eng.stabilize(records, confirmed_ids=list(confirmed))
    merged = rep.get("compression", {}).get("merged", []) or []
    prune = (rep.get("prune_candidates") or {}).get("candidates", []) or []
    conflicts = (rep.get("conflicts") or {}).get("conflicts", []) or []
    evals = rep.get("evaluation", []) or []
    low_weight = [e for e in evals
                  if (e or {}).get("mode") != "error_frame"
                  and float((e or {}).get("weight", 1.0) or 1.0) < 0.3]
    return {
        "total": rep.get("total", len(records)),
        "merge_groups": [
            {"primary": m.get("primary_id", ""),
             "merged_ids": m.get("merged_ids", []),
             "reason": m.get("reason", "")[:120],
             "primary_summary": meta.get(m.get("primary_id", ""), "")[:60]}
            for m in merged[:limit_detail]
        ],
        "prune_candidates": [
            {"id": c, "summary": meta.get(c, "")[:60]}
            for c in prune[:limit_detail]
        ],
        "conflicts": [
            {"type": c.get("conflict_type", ""),
             "ids": c.get("record_ids", []),
             "reason": c.get("reason", "")[:120],
             "summaries": [meta.get(x, "")[:40] for x in (c.get("record_ids") or [])[:3]]}
            for c in conflicts[:limit_detail]
        ],
        "low_weight_count": len(low_weight),
        "note": "只读审计：压缩/淘汰候选/冲突为提案，执行需显式（owner 审批）。",
    }


def cli_print(memory) -> None:
    import json

    rep = stabilize_report(memory)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
