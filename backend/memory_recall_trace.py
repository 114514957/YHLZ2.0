# -*- coding: utf-8 -*-
"""记忆召回注入追踪（可观测）。

为什么要有：目前 `target_entry` 里的召回整段包在 `try/except: pass` 里，
**出错会静默变成"没有记忆"**，谁也发现不了（台账 1233）。
本模块把"这一轮查了什么、喂了哪几条、为什么没喂"记成一行 JSONL。

落盘：`cache/recall_trace.jsonl`，超过 `YHLZ_RECALL_TRACE_MAX`（默认 5000 行）自动轮转。
可用 `YHLZ_RECALL_TRACE=0` 关闭。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

__all__ = ["trace", "path"]

_LOCK = threading.Lock()
_MAX = int(os.getenv("YHLZ_RECALL_TRACE_MAX", "5000"))
_ENABLED = os.getenv("YHLZ_RECALL_TRACE", "1") != "0"
_PATH = Path(__file__).resolve().parent.parent / "cache" / "recall_trace.jsonl"


def path() -> Path:
    return _PATH


def _rotate(p: Path) -> None:
    try:
        if not p.exists():
            return
        with p.open("rb") as f:
            n = sum(1 for _ in f)
        if n >= _MAX:
            os.replace(p, p.with_suffix(".jsonl.1"))
    except Exception:  # noqa: BLE001
        pass


def trace(*, turn_id: str = "", channel: str = "", query: str = "",
          hits: list[dict] | None = None, allowed: bool = True,
          why: str = "", mode: str = "v2", ms: float = 0.0) -> None:
    """记一行。任何异常都吞掉——追踪不能影响回复。"""
    if not _ENABLED:
        return
    hits = hits or []
    rec = {
        "ts": round(time.time(), 3),
        "turn": str(turn_id)[:40],
        "channel": str(channel)[:24],
        "q": (query or "")[:160],
        "allowed": bool(allowed),
        "why": str(why)[:40],
        "mode": str(mode)[:12],
        "n": len(hits),
        "ids": [str(h.get("id")) for h in hits][:5],
        "scores": [round(float(h.get("score", 0.0)), 3) for h in hits][:5],
        "ms": round(float(ms), 1),
    }
    try:
        with _LOCK:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotate(_PATH)
            with _PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
