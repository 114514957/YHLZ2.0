"""Snapshot CLI: python tools/snapshot.py create [tag] | list | restore <ts>"""
from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend import snapshots  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    cmd = a[0] if a else "list"
    if cmd == "create":
        tag = a[1] if len(a) > 1 else ""
        print("snapshot:", snapshots.create(tag))
    elif cmd == "list":
        for m in snapshots.list_snapshots():
            print(f"{m.get('ts')}  tag={m.get('tag','')}  "
                  f"files={list((m.get('files') or {}).keys())}")
    elif cmd == "restore" and len(a) > 1:
        print(json.dumps(snapshots.restore(a[1]), ensure_ascii=False))
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
