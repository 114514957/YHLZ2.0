# -*- coding: utf-8 -*-
"""「最近回合」数据层（台账 1254）：把调用账与召回追踪按时间并起来。

为什么要它：今天排查"私聊没回话/召回没生效"时，我要人工翻两个 jsonl 再对时间。
一屏合并后，问句、注入条数、注入了哪几条、via（trigger/vector）、花了多少钱，一起看。
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USAGE = ROOT / "cache" / "llm_usage.jsonl"
TRACE = ROOT / "cache" / "recall_trace.jsonl"

__all__ = ["recent", "summary_line"]


def _tail(path: Path, n: int) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    return out


def recent(limit: int = 20) -> dict:
    """返回最近回合：每个召回记录配对"它之后最近的一次调用账"。"""
    tr = _tail(TRACE, max(limit * 3, 60))
    us = _tail(USAGE, max(limit * 3, 60))
    us.sort(key=lambda r: float(r.get("ts") or 0))
    tr.sort(key=lambda r: float(r.get("ts") or 0))

    rows = []
    for t in tr[-limit:]:
        ts = float(t.get("ts") or 0)
        nxt = next((u for u in us if float(u.get("ts") or 0) >= ts), None)
        rows.append({
            "ts": round(ts, 3),
            "time": time.strftime("%m-%d %H:%M:%S", time.localtime(ts)) if ts else "",
            "channel": t.get("channel", ""),
            "q": str(t.get("q") or "")[:80],
            "allowed": bool(t.get("allowed")),
            "why": t.get("why", ""),
            "n": int(t.get("n") or 0),
            "ids": (t.get("ids") or [])[:3],
            "scores": (t.get("scores") or [])[:3],
            "ms_recall": t.get("ms"),
            "cost": (nxt or {}).get("cost"),
            "tokens_in": (nxt or {}).get("in"),
            "tokens_out": (nxt or {}).get("out"),
            "sec": (nxt or {}).get("sec"),
        })
    return {"rows": rows,
            "usage": _tail(USAGE, 1)[-1] if us else {},
            "count": len(rows)}


def summary_line() -> str:
    d = recent(5)
    if not d["rows"]:
        return "（还没有回合记录）"
    parts = []
    for r in d["rows"][-3:]:
        parts.append("%s n=%d ¥%s" % (r["time"][-8:], r["n"],
                                      r["cost"] if r["cost"] is not None else "?"))
    return "；".join(parts)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = recent(10)
    print("最近 %d 条：" % d["count"])
    for r in d["rows"]:
        print("  %s %-8s n=%d via=%s ¥%s in=%s  %s"
              % (r["time"], r["channel"], r["n"], ",".join(r["ids"])[:24],
                 r["cost"], r["tokens_in"], r["q"][:36]))
