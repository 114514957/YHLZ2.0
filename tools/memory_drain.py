"""Drain leftover L1->L2 summary backlog (ledger 1096, 2026-11-05).

L1 -> L2 summarisation is **event-driven**: ``ConversationSession`` kicks the
summary scheduler only after a NEW turn in that channel. A channel that goes
silent keeps its pending queue forever. On 2026-11-05 the queues were:

    console              pending 25   (last turn 2026-10-22)
    qq_p2258374446       pending 31   (last turn 2026-10-15)

This tool drains them explicitly instead of adding a background timer (the
autonomy flag is deliberately on — no autonomous LLM work).

Usage:
    python tools/memory_drain.py              # dry run: list scopes/pending
    python tools/memory_drain.py --apply      # drain (local LLM, writes L2)
    python tools/memory_drain.py --apply --scope console
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.env_loader import ensure_env_loaded  # noqa: E402


def scopes_with_pending() -> list[dict]:
    out: list[dict] = []
    for p in sorted((ROOT / "cache" / "memstore").glob("memstore.db.l1*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        pending = d.get("pending") or []
        if pending:
            out.append({"file": p.name, "scope": str(d.get("scope") or ""),
                        "pending": len(pending)})
    return out


def drain(scope: str) -> dict:
    from backend.target_entry import ConversationSession

    ensure_env_loaded()
    s = ConversationSession(channel=scope)
    before = len(getattr(s.memory, "_pending_dropped", []) or [])
    if not getattr(s.memory, "_summary_pending", False):
        return {"scope": scope, "before": before, "after": before,
                "ok": True, "note": "not_pending"}
    s._last_turn_ts = 0.0  # scheduler idle gate: pretend we have been idle

    async def go() -> None:
        task = s._memory_summary_scheduler.kick()
        if task is not None:
            await task

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        return {"scope": scope, "before": before, "after": before,
                "ok": False, "error": type(exc).__name__ + ": " + str(exc)[:160]}
    after = len(getattr(s.memory, "_pending_dropped", []) or [])
    err = (getattr(s.memory, "_summary_error", "")
           or s._memory_summary_scheduler.last_error or "")
    return {"scope": scope, "before": before, "after": after,
            "ok": after < before, "error": str(err)[:160]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually drain (writes L2)")
    ap.add_argument("--scope", default="", help="only this scope")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    items = scopes_with_pending()
    if args.scope:
        items = [i for i in items if i["scope"] == args.scope]
    print(json.dumps({"pending_scopes": items}, ensure_ascii=False, indent=1))
    if not args.apply:
        print("dry run — re-run with --apply to drain")
        return 0
    results = []
    for item in items:
        try:
            results.append(drain(item["scope"]))
        except Exception as exc:  # noqa: BLE001
            results.append({"scope": item["scope"], "ok": False,
                            "error": type(exc).__name__ + ": " + str(exc)[:160]})
    print(json.dumps({"results": results}, ensure_ascii=False, indent=1))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
