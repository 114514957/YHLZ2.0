"""把 L2 记忆摘要回填进 kg_v2（2026-11-18）。

用法：
  python tools/kg_backfill.py [--limit 40] [--min-importance 0]
已有 doc 哈希幂等；重复跑只会给已有关系加 hits。
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import kg_v2  # noqa: E402

MEM = ROOT / "cache" / "memstore" / "memstore.db"


def rows(limit: int, min_imp: int):
    con = sqlite3.connect(str(MEM))
    try:
        return con.execute(
            "select id, type, importance, summary from l2_items "
            "where status='active' and importance>=? and length(summary)>=24 "
            "order by importance desc, created_at desc limit ?",
            (min_imp, limit)).fetchall()
    finally:
        con.close()


def ledger_rows(limit: int):
    from backend.ledger_index_v2 import parse_records

    recs = [r for r in parse_records()
            if r["kind"] in ("决策", "结论") and 80 <= len(r["body"]) <= 2500]
    recs.sort(key=lambda r: r["rec"], reverse=True)
    return [(r["rec"], r["kind"], r["title"], r["body"]) for r in recs[:limit]]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--min-importance", type=int, default=0)
    ap.add_argument("--source", choices=("l2", "ledger"), default="l2")
    args = ap.parse_args()
    if args.source == "ledger":
        items = [(rid, kind, 0, f"{title}\n{body[:1200]}")
                 for rid, kind, title, body in ledger_rows(args.limit)]
    else:
        items = rows(args.limit, args.min_importance)
    print(f"回填 {len(items)} 条 {args.source} -> {kg_v2.DB_PATH}")
    total = 0
    for i, (mid, typ, imp, summary) in enumerate(items, start=1):
        n = await kg_v2.ingest(summary, source=f"{args.source}:{mid}", force=True)
        total += n
        print(f"[{i}/{len(items)}] {mid} {typ} imp={imp} -> {n} triples", flush=True)
    print("done triples", total)
    print("stats", kg_v2.stats())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(main()))
