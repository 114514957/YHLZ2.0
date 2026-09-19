"""Notification dedupe / rate-limit (F5, ledger 0436).

Autonomy and consolidation notices used to repeat verbatim every cycle
(the owner saw "任务完成汇报" / "[自主]" noise). Keep a small fingerprint
ledger: identical or near-identical text inside `cooldown` is dropped, and
each kind is capped per 24h window. State: cache/notify_guard.json.

Never raises: any failure fails open (notification allowed) so a broken
guard can never silence Yuanheng entirely.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE_FILE = _ROOT / "cache" / "notify_guard.json"

DEFAULT_COOLDOWN = 6 * 3600.0
DEFAULT_MAX_PER_DAY = 4
_KEEP = 200
_WINDOW = 72 * 3600.0


def _fp(text: str) -> str:
    norm = re.sub(r"[\s\u3000]+", "", str(text or ""))[:160]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def allow(kind: str, text: str, cooldown: float = DEFAULT_COOLDOWN,
          max_per_day: int = DEFAULT_MAX_PER_DAY, now: float | None = None,
          state_file: pathlib.Path | None = None) -> bool:
    """True if this notice may be pushed (and records the decision)."""
    ts = time.time() if now is None else float(now)
    path = pathlib.Path(state_file) if state_file else STATE_FILE
    try:
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        items = [it for it in (data.get(kind) or [])
                 if isinstance(it, dict)
                 and ts - float(it.get("ts") or 0) < _WINDOW]
        fp = _fp(text)
        if any(it.get("fp") == fp
               and ts - float(it.get("ts") or 0) < float(cooldown)
               for it in items):
            return False
        day_start = ts - 24 * 3600
        if int(max_per_day) > 0 and sum(
                1 for it in items
                if float(it.get("ts") or 0) >= day_start) >= int(max_per_day):
            return False
        items.append({"fp": fp, "ts": ts})
        data[kind] = items[-_KEEP:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return True
