"""Ledger QA full-flow runner: ask real model, judge against bank keys.

Usage: python tools/ledger_qa_run.py [--limit N] [--record]
True end-to-end: question -> model tool decisions (ledger_search/recall)
-> answer -> keyword verdict vs the ledger-ground-truth bank.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from typing import Optional

sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ")


def _setup() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def main(argv: Optional[list[str]] = None) -> int:
    _setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--record", action="store_true",
                        help="append a QA line to the ledger")
    args = parser.parse_args(argv)

    from backend.env_loader import ensure_env_loaded

    ensure_env_loaded()
    from backend.target_entry import ConversationSession
    from tools.ledger_qa_bank import QA_BANK, verify

    results = []
    for entry in QA_BANK[: args.limit]:
        session = ConversationSession(max_tool_rounds=1)
        info = await session.run_turn(entry["q"])
        ok, hit = verify(entry["q"], info["answer"])
        tools = ",".join(u["name"] for u in info["tool_uses"])
        errors = ";".join(
            f"{u['name']}:{u['error']}" for u in info["tool_uses"] if not u["ok"]
        )
        results.append((ok, entry["q"], hit, tools))
        print(f"{'PASS' if ok else 'FAIL'} | {entry['q']}")
        print(f"      answer: {info['answer'][:150]}")
        print(f"      tools: {tools or '-'} | hit: {hit}")
        if errors:
            print(f"      tool-errors: {errors[:200]}")
    n_pass = sum(1 for r in results if r[0])
    print(f"\n=== {n_pass}/{len(results)} passed (>=13 required) ===")
    return 0 if n_pass >= 13 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
