"""Style-signal capture (ledger 0167): observe the Dad's style corrections in
conversation and store them as low-weight preference items, feeding the future
style-evolution engine (docs/风格进化设计.md).  Rule-based first; no LLM cost.

Every hit is stored WITHOUT interrupting the conversation (importance 4).
"""

from __future__ import annotations

import re
from typing import Optional

_PATTERNS: list[tuple[str, list[str]]] = [
    ("casual", ["说人话", "别官方", "别那么严肃", "别太严肃", "太严肃", "随意点",
                "轻松点", "别文绉绉", "口语化", "别端着"]),
    ("concise", ["太长了", "太长", "简短", "简洁", "说重点", "短一点", "精炼", "啰嗦"]),
    ("detailed", ["详细点", "展开说", "更详细", "具体点", "深入些"]),
    ("warm", ["热情点", "活泼点", "温暖一点", "有人情味", "像人一样", "柔和"]),
    ("poetic", ["美一点", "诗意", "文艺点"]),
]

_COMPILED = [(feature, [k for k in keys]) for feature, keys in _PATTERNS]


def detect_style_signals(text: str) -> list[str]:
    """Return style feature tags the user just asked for (deduped, in order)."""
    out: list[str] = []
    if not text:
        return out
    for feature, keys in _COMPILED:
        if any(k in text for k in keys) and feature not in out:
            out.append(feature)
    return out


def capture_style_signal(text: str, memory: Optional[object] = None) -> list[str]:
    """Store style-preference items for any detected signals (best-effort)."""
    signals = detect_style_signals(text)
    if not signals or memory is None:
        return signals
    from backend.target_scheduler_tools import memory_save

    for sig in signals:
        try:
            memory_save(
                f"风格偏好：老爹希望更{sig}（对话风格纠偏信号）",
                kind="preference", importance=4, service=memory,
            )
        except Exception:
            pass
    return signals
