"""QQ outbox (P2e): durable, retry-safe proactive messages.

The bridge must not delete an item before OneBot acknowledges ``send_msg``.
``peek`` + ``ack`` provides that at-least-once boundary; the older ``drain``
API remains for compatibility with existing callers/tests.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import threading
import time
import uuid

from backend.qq_bridge_state import path as _bridge_path

_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTBOX = _bridge_path("outbox.jsonl", _ROOT / "cache" / "qq_outbox.jsonl")
_LOCK = threading.RLock()


def _item_key(item: dict) -> str:
    value = str(item.get("id") or "").strip()
    if value:
        return value
    payload = json.dumps({k: v for k, v in item.items() if k != "id"},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "legacy:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _read_lines() -> list[tuple[str, dict]]:
    if not OUTBOX.exists():
        return []
    try:
        raw_lines = OUTBOX.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in raw_lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                out.append((line, item))
        except Exception:
            # A malformed line is not deliverable and is intentionally omitted
            # when the next atomic rewrite happens.
            continue
    return out


def _atomic_write(items: list[dict]) -> None:
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTBOX.with_name(OUTBOX.name + ".tmp")
    content = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items)
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(OUTBOX)


def push(text: str, kind: str = "proactive") -> None:
    text = str(text or "").strip()
    if not text:
        return
    try:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        item = {"id": uuid.uuid4().hex, "ts": time.time(), "kind": str(kind),
                "text": text[:800]}
        with _LOCK:
            with OUTBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        pass


def peek(limit: int = 5) -> list[dict]:
    """Return pending items without removing them.

    The caller must call :func:`ack` only after the remote API confirms the
    send.  Items remain on disk if the process or socket dies mid-send.
    """
    try:
        limit = max(0, int(limit))
        if not limit:
            return []
        with _LOCK:
            result = []
            for _line, item in _read_lines():
                item = dict(item)
                item.setdefault("id", _item_key(item))
                result.append(item)
                if len(result) >= limit:
                    break
            return result
    except Exception:
        return []


def ack(items: list[dict] | dict) -> int:
    """Remove exactly the acknowledged items; return the number removed."""
    if isinstance(items, dict):
        items = [items]
    keys = {_item_key(i) for i in items if isinstance(i, dict)}
    if not keys:
        return 0
    try:
        with _LOCK:
            current = _read_lines()
            kept = [item for _line, item in current if _item_key(item) not in keys]
            removed = len(current) - len(kept)
            if removed:
                _atomic_write(kept)
            return removed
    except Exception:
        return 0


def drain(limit: int = 5) -> list[dict]:
    """Legacy destructive read. New bridge code should use ``peek`` + ``ack``."""
    try:
        limit = max(0, int(limit))
        if not limit:
            return []
        with _LOCK:
            current = _read_lines()
            out = [dict(item) for _line, item in current[:limit]]
            _atomic_write(current[limit:])
            return out
    except Exception:
        return []
