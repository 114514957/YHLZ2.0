"""Backfill vector side-table for existing L2 items, then demo semantic recall.

Usage: python tools/vec_backfill.py [--query 想测试的话]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=None)
    a = ap.parse_args()
    from backend.vector_memory import MEMORY_DB, _conn, embed

    con = sqlite3.connect(str(MEMORY_DB))
    rows = con.execute(
        "SELECT id, keywords, summary, status FROM l2_items"
        " WHERE status != 'archive'").fetchall()
    con.close()
    vc = _conn()
    have = {r[0] for r in vc.execute("SELECT id FROM vec WHERE scope='l2'")}
    todo = [r for r in rows if r[0] not in have]
    if todo:
        texts = [f"{r[2]} {r[1]}".strip()[:256] for r in todo]
        vs = embed(texts)
        for r, v in zip(todo, vs):
            vc.execute("INSERT OR REPLACE INTO vec(id,scope,vec) VALUES(?,?,?)",
                       (r[0], "l2", v.tobytes()))
        vc.commit()
    vc.close()
    print(f"vec L2: 共 {len(rows)} 条，新增 {len(todo)}（已有 {len(have)}）",
          flush=True)
    if a.query:
        from backend.vector_memory import semantic_l2

        print(f"\n语义查询：{a.query}")
        for it in semantic_l2(a.query, top=6):
            print(f"  [{it['score']}|{it['importance']}|{it['type']}] "
                  f"{it['summary'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
