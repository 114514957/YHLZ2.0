"""CLI for memory projection audit/rebuild.

Safe default: audit only.  Vector rebuild requires --allow-model explicitly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.memory_index_audit import (
    audit, dumps, prune_vector_stale, rebuild_fts, rebuild_keyword, rebuild_vector,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Audit/rebuild YHLZ memory indexes")
    p.add_argument("command", choices=("audit", "rebuild-fts", "rebuild-keyword", "rebuild-vector", "prune-vector-stale"))
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--kw-db", type=Path)
    p.add_argument("--vec-db", type=Path)
    p.add_argument("--scope")
    p.add_argument("--source", default="l2")
    p.add_argument("--clear-source", action="store_true")
    p.add_argument("--allow-model", action="store_true")
    p.add_argument("--apply", action="store_true", help="apply projection cleanup (default is dry-run)")
    args = p.parse_args()
    if args.command == "audit":
        result = audit(args.db, kw_db_path=args.kw_db, vec_db_path=args.vec_db,
                       scope=args.scope, keyword_source=args.source)
    elif args.command == "rebuild-fts":
        result = rebuild_fts(args.db)
    elif args.command == "rebuild-keyword":
        if args.kw_db is None:
            p.error("rebuild-keyword requires --kw-db")
        result = rebuild_keyword(args.db, kw_db_path=args.kw_db,
                                 keyword_source=args.source, clear_source=args.clear_source)
    elif args.command == "rebuild-vector":
        if args.vec_db is None:
            p.error("rebuild-vector requires --vec-db")
        result = rebuild_vector(args.db, vec_db_path=args.vec_db,
                                scope=args.scope, allow_model=args.allow_model)
    else:
        if args.vec_db is None:
            p.error("prune-vector-stale requires --vec-db")
        result = prune_vector_stale(args.db, vec_db_path=args.vec_db,
                                    scope=args.scope, apply=args.apply)
    print(dumps(result))
    return 0 if result.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
