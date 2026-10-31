"""Review/version controls for the L3 cognition foundation.

``list`` and ``show`` do not edit foundation content, but may initialize the
version schema. Use memory_health for strictly read-only checks. ``recover``
and ``revert`` require --confirm and a reason; they never delete history or
overwrite an external edit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.persona_versions import PersonaConflict, PersonaVersions
from backend.target_memory import COGNITION_FILE, DEFAULT_DB


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--foundation", type=Path, default=COGNITION_FILE)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("id")
    for name in ("recover", "revert"):
        cmd = sub.add_parser(name)
        cmd.add_argument("id")
        cmd.add_argument("--reason", required=True)
        cmd.add_argument("--confirm", action="store_true")
    args = p.parse_args(argv)
    if not args.db.is_file():
        p.error("selected L2 database does not exist")
    versions = PersonaVersions(args.db, args.foundation)
    try:
        if args.action == "list":
            result = versions.list()
        elif args.action == "show":
            result = versions.get(args.id)
        else:
            if not args.confirm:
                p.error("no change: use --confirm after reviewing the change and evidence")
            if args.action == "recover":
                result = {"id": args.id, "state": versions.recover(args.id)}
            else:
                result = {"id": versions.revert(args.id, reason=args.reason),
                          "operation": "revert"}
    except (KeyError, PersonaConflict, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
