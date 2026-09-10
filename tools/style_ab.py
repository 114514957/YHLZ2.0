"""Style-injection A/B: same question, style_inject OFF vs ON.

Seeds a 'concise' preference (threshold lowered to 0.2 for this probe since
identical signals dedup in memory), then compares two sessions with separate
but identically-seeded memories. Usage: python tools/style_ab.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import backend.target_style as style  # noqa: E402
from backend.target_entry import ConversationSession  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402
from backend.target_scheduler_tools import setup_scheduler_capabilities  # noqa: E402

style._INJECT_THRESHOLD = 0.2  # probe only


def _seeded_mem() -> TargetMemoryService:
    tmp = pathlib.Path(tempfile.mkdtemp())
    mem = TargetMemoryService(db_path=tmp / "m.db")
    style.capture_style_signal("太长了，说重点", mem)
    return mem


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reg = setup_scheduler_capabilities()
    q = "介绍一下你自己，还有你最近在做的事。"

    def run(inject: bool) -> str:
        mem = _seeded_mem()
        s = ConversationSession(memory=mem, registry=reg, channel="private")
        s.style_inject = inject
        lines = style.active_style_lines(style.style_ema(mem.recall("风格偏好", 30)))
        print(f"[inject={inject}] style_lines={lines}")
        return str(asyncio.run(s.run_turn(q))["answer"])

    off = run(False)
    on = run(True)
    print("\n=== OFF ===\n" + off)
    print("\n=== ON ===\n" + on)
    print(f"\nlen OFF={len(off)} ON={len(on)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
