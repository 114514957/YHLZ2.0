"""QQ outbox (P2e): a small queue the daemon/autonomy appends to, which the QQ
bridge drains and sends to the master — so Yuanheng can proactively reach out
(drive-driven) when QQ is online.

File: cache/qq_outbox.jsonl  (one JSON per line). Bridge drains + clears.
"""
from __future__ import annotations

import json
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTBOX = _ROOT / "cache" / "qq_outbox.jsonl"


def push(text: str, kind: str = "proactive") -> None:
    text = str(text or "").strip()
    if not text:
        return
    try:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind,
                                "text": text[:800]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def drain(limit: int = 5) -> list[dict]:
    """Return up to `limit` pending items and KEEP the rest (atomic rewrite).

    Earlier versions cleared the whole file and returned only lines[:limit],
    silently dropping everything past the limit (ledger 0300)."""
    if not OUTBOX.exists():
        return []
    try:
        lines = OUTBOX.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    rest: list[str] = []
    for ln in lines:
        if len(out) < limit:
            try:
                out.append(json.loads(ln))
                continue
            except Exception:
                continue  # drop malformed line
        rest.append(ln)
    try:
        tmp = OUTBOX.with_suffix(".tmp")
        tmp.write_text(("\n".join(rest) + "\n") if rest else "", encoding="utf-8")
        tmp.replace(OUTBOX)
    except Exception:
        pass
    return out
