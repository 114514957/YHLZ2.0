"""TCM v1 migration (ledger 0438): backfill `stance` for legacy memory items.

A1 source grading rule (dry-run by default):
  老爹/owner/user-approved  -> fact
  agent/元亨                -> opinion
  群聊/qq/QQ/external/group -> speculation
  anything else (legacy "") -> left ungraded ('')

Usage:
  python tools/memory_migrate_tcm.py            # dry-run, prints counts
  python tools/memory_migrate_tcm.py --apply    # backs up db then writes
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.target_memory import (  # noqa: E402
    DEFAULT_DB, EXTERNAL_SOURCES, _FACT_SOURCES, _OPINION_SOURCES,
)


def plan_rows(con: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT id, COALESCE(source,'') FROM l2_items "
        "WHERE COALESCE(stance,'')=''").fetchall()
    out: list[tuple[str, str]] = []
    for iid, src in rows:
        s = str(src or "").strip()
        if s in _FACT_SOURCES:
            out.append((iid, "fact"))
        elif s in _OPINION_SOURCES:
            out.append((iid, "opinion"))
        elif s in EXTERNAL_SOURCES:
            out.append((iid, "speculation"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    db = Path(a.db)
    if not db.exists():
        print(f"db not found: {db}")
        return 1
    con = sqlite3.connect(str(db))
    try:
        total = con.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0]
        planned = plan_rows(con)
    finally:
        con.close()
    by = {}
    for _, stance in planned:
        by[stance] = by.get(stance, 0) + 1
    print(f"db={db}")
    print(f"l2 total={total} to-grade={len(planned)} breakdown={by}")
    if not a.apply:
        print("dry-run; pass --apply to write")
        return 0
    backup = db.with_name(db.name + f".bak-tcm-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(db, backup)
    print(f"backup -> {backup}")
    con = sqlite3.connect(str(db))
    try:
        con.executemany("UPDATE l2_items SET stance=? WHERE id=?",
                        [(stance, iid) for iid, stance in planned])
        con.commit()
        done = con.execute(
            "SELECT COUNT(*) FROM l2_items WHERE COALESCE(stance,'')!=''"
        ).fetchone()[0]
    finally:
        con.close()
    print(f"applied: {len(planned)} rows; graded now={done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
