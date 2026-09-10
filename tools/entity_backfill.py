"""Backfill the entity/relation graph from existing L2 memory.

Usage: python tools/entity_backfill.py [--limit N]
"""
from __future__ import annotations

import asyncio
import pathlib
import sqlite3
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend import entity_graph  # noqa: E402
from backend.target_memory import DEFAULT_DB  # noqa: E402


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 200
    if not pathlib.Path(DEFAULT_DB).exists():
        print("no memory db:", DEFAULT_DB)
        return 1
    con = sqlite3.connect(str(DEFAULT_DB))
    rows = con.execute(
        "SELECT summary,keywords FROM l2_items WHERE status!='archive' "
        "ORDER BY importance DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    print(f"scanning {len(rows)} L2 items …")
    total = 0
    for i, (summary, keywords) in enumerate(rows, 1):
        text = f"{summary} {keywords}".strip()
        triples = await entity_graph.extract_triples(text)
        total += entity_graph.upsert(triples)
        if i % 20 == 0:
            print(f"  {i}/{len(rows)} triples={total}")
            time.sleep(0.2)
    print(f"done: {total} triples from {len(rows)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
