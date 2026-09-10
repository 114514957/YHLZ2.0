"""Snapshot & rollback for Yuanheng's evolving state (design v1 §2).

Captures the state files that define "who she is" (cognition foundation,
persona dims, style signals, entity graph, L2 memory db) so growth can be
inspected and rolled back ("长歪了可调，保留回滚能力").

Usage:
  from backend import snapshots
  snapshots.create("before-consolidate")
  snapshots.list_snapshots()
  snapshots.restore("<ts>")
"""
from __future__ import annotations

import json
import pathlib
import shutil
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP_DIR = _ROOT / "cache" / "snapshots"
KEEP = 20


def _targets() -> dict[str, pathlib.Path]:
    from backend.target_memory import DEFAULT_DB

    return {
        "cognition": _ROOT / "docs" / "元亨认知根基.md",
        "persona_dims": _ROOT / "data" / "persona_dims.json",
        "style_signals": _ROOT / "cache" / "style_signals.json",
        "entity_graph": _ROOT / "cache" / "entity_graph.db",
        "memory_db": pathlib.Path(DEFAULT_DB),
    }


def create(tag: str = "") -> str:
    """Snapshot current state; returns the snapshot dir ('' on failure)."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = SNAP_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"ts": ts, "tag": str(tag), "time": time.time(), "files": {}}
    for name, src in _targets().items():
        try:
            if src.exists():
                shutil.copy2(str(src), str(dest / (name + src.suffix)))
                manifest["files"][name] = src.name
        except Exception:
            pass
    try:
        (dest / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        return ""
    prune()
    return str(dest)


def list_snapshots() -> list[dict]:
    out = []
    if not SNAP_DIR.exists():
        return out
    for d in sorted(SNAP_DIR.iterdir(), reverse=True):
        m = d / "manifest.json"
        if d.is_dir() and m.exists():
            try:
                out.append(json.loads(m.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def restore(ts: str) -> dict:
    """Restore a snapshot by ts; returns {restored:[...], missing:[...]}."""
    src = SNAP_DIR / ts
    if not src.exists():
        return {"ok": False, "error": "snapshot not found: " + str(ts)}
    restored, missing = [], []
    for name, target in _targets().items():
        cand = list(src.glob(name + ".*"))
        if not cand:
            missing.append(name)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(cand[0]), str(target))
            restored.append(name)
        except Exception:
            missing.append(name)
    return {"ok": True, "restored": restored, "missing": missing}


def prune(keep: int = KEEP) -> None:
    try:
        dirs = sorted([d for d in SNAP_DIR.iterdir() if d.is_dir()], reverse=True)
        for d in dirs[keep:]:
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
