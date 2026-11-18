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


def ledger_rows(limit: int, skip_existing: bool = True):
    from backend.ledger_index_v2 import parse_records

    recs = [r for r in parse_records()
            if r["kind"] in ("决策", "结论") and 80 <= len(r["body"]) <= 2500]
    recs.sort(key=lambda r: r["rec"], reverse=True)
    if skip_existing:
        with kg_v2._conn() as con:
            done = {str(r[0]) for r in con.execute(
                "SELECT source FROM docs WHERE source LIKE 'ledger:%'")}
            done |= {str(r[0]) for r in con.execute(
                "SELECT source FROM processed WHERE source LIKE 'ledger:%'")}
        recs = [r for r in recs if f"ledger:{r['rec']}" not in done]
    return [(r["rec"], r["kind"], r["title"], r["body"]) for r in recs[:limit]]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--min-importance", type=int, default=0)
    ap.add_argument("--source", choices=("l2", "ledger"), default="l2")
    ap.add_argument("--batch", type=int, default=1,
                    help="每次 LLM 调用处理几段（>1 时用批量抽取，快很多）")
    ap.add_argument("--no-skip", action="store_true",
                    help="ledger 源：不跳过已入库的记录（默认跳过）")
    args = ap.parse_args()
    if args.source == "ledger":
        # 2026-11-18：原来只喂 body[:350]，台账 80-2500 字，后面的事实全丢
        # （实测 85% 的记录只剩 0 triples）。改成最多 1400 字，超长再截。
        items = [(rid, kind, 0, f"{title}\n{body[:1400]}")
                 for rid, kind, title, body in
                 ledger_rows(args.limit, skip_existing=not args.no_skip)]
    else:
        items = rows(args.limit, args.min_importance)
    print(f"回填 {len(items)} 条 {args.source} -> {kg_v2.DB_PATH}")
    total = 0
    if args.batch > 1:
        step = max(2, int(args.batch))
        for start in range(0, len(items), step):
            chunk = items[start:start + step]
            texts = [c[3][:700] for c in chunk]
            groups = await kg_v2.extract_batch(texts)
            for (mid, typ, imp, _summary), text, triples in zip(chunk, texts, groups):
                n = kg_v2.upsert(triples, text, source=f"{args.source}:{mid}")
                kg_v2.mark_processed(f"{args.source}:{mid}")
                total += n
                print(f"[{start + 1}-{start + len(chunk)}/{len(items)}] "
                      f"{mid} -> {n} triples", flush=True)
    else:
        for i, (mid, typ, imp, summary) in enumerate(items, start=1):
            n = await kg_v2.ingest(summary, source=f"{args.source}:{mid}", force=True)
            kg_v2.mark_processed(f"{args.source}:{mid}")
            total += n
            print(f"[{i}/{len(items)}] {mid} {typ} imp={imp} -> {n} triples", flush=True)
    print("done triples", total)
    print("stats", kg_v2.stats())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(main()))
