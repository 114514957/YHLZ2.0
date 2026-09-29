"""Backup production memory DBs and session archives (Step 4 prep).

Creates timestamped backups before daemon/QQ bridge restart.
Supports --restore for rollback.

Usage:
    python tools/backup_memory_data.py           # backup
    python tools/backup_memory_data.py --restore  # list backups
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "cache" / "backups" / "memory_qq"


def find_targets() -> list[Path]:
    """Find all production DBs and session archives."""
    targets = []
    # L2 databases
    for db in (ROOT / "cache" / "memstore").glob("*.db"):
        targets.append(db)
    for db in (ROOT / "cache" / "qq_groups").glob("*.db"):
        targets.append(db)
    # L1 caches
    for f in (ROOT / "cache" / "memstore").glob("*.l1*.json"):
        targets.append(f)
    for f in (ROOT / "cache" / "qq_groups").glob("*.l1*.json"):
        targets.append(f)
    # Session archives
    for f in (ROOT / "cache" / "sessions").glob("*.json"):
        targets.append(f)
    return sorted(targets)


def backup() -> dict:
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = BACKUP_DIR / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"timestamp": ts, "files": []}
    for src in find_targets():
        rel = src.relative_to(ROOT / "cache")
        dst = out_dir / str(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest["files"].append({
            "source": str(src),
            "backup": str(dst),
            "size": src.stat().st_size,
        })
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"backup_dir": str(out_dir), "count": len(manifest["files"]),
            "total_bytes": sum(f["size"] for f in manifest["files"])}


def list_backups() -> list[dict]:
    out = []
    for d in sorted(BACKUP_DIR.glob("*"),
                    key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        m = d / "manifest.json"
        if m.exists():
            data = json.loads(m.read_text(encoding="utf-8"))
            out.append({"dir": str(d), "timestamp": data.get("timestamp"),
                        "count": len(data.get("files", [])),
                        "total_bytes": sum(f["size"] for f in data.get("files", []))})
    return out


def restore(backup_ts: str) -> dict:
    """Restore from a specific backup (by timestamp)."""
    src_dir = BACKUP_DIR / backup_ts
    manifest_path = src_dir / "manifest.json"
    if not manifest_path.exists():
        return {"error": f"backup not found: {src_dir}"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored = 0
    for item in manifest["files"]:
        src = Path(item["backup"])
        dst = Path(item["source"])
        if src.exists():
            shutil.copy2(src, dst)
            restored += 1
    return {"restored": restored, "backup_dir": str(src_dir)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", default=None, help="backup timestamp to restore")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        backups = list_backups()
        print(json.dumps(backups, ensure_ascii=False, indent=1))
        return 0

    if args.restore:
        result = restore(args.restore)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    result = backup()
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
