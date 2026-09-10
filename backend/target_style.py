"""Style-signal capture (ledger 0167): observe the Dad's style corrections in
conversation and store them as low-weight preference items, feeding the future
style-evolution engine (docs/风格进化设计.md).  Rule-based first; no LLM cost.

Every hit is stored WITHOUT interrupting the conversation (importance 4).
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Optional

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_COUNTS = _PROJECT_ROOT / "cache" / "style_signals.json"

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


STYLE_DIMS = ("casual", "concise", "detailed", "warm", "poetic")
EMA_ALPHA = 0.3
_INJECT_THRESHOLD = 0.35


def style_ema(items: list[dict], alpha: float = EMA_ALPHA) -> dict[str, float]:
    """Aggregate style-preference items into EMA tendency values (-1..+1).

    Each item summary carries a style tag (风格偏好：老爹希望更<tag>…);
    counts map to tendency: n hits on a dim push it toward +1.
    """
    values: dict[str, float] = {d: 0.0 for d in STYLE_DIMS}
    for it in items:
        summary = str(it.get("summary", ""))
        for dim in STYLE_DIMS:
            if f"更{dim}" in summary:
                values[dim] += alpha * (1.0 - abs(values[dim])) * (
                    1.0 if it.get("direction", 1) > 0 else -1.0)
    return {k: round(min(0.99, max(-0.99, v)), 3) for k, v in values.items()}


def _load_counts() -> dict:
    try:
        return json.loads(STYLE_COUNTS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bump_counts(signals: list[str]) -> None:
    if not signals:
        return
    counts = _load_counts()
    for s in signals:
        counts[s] = int(counts.get(s, 0)) + 1
    try:
        STYLE_COUNTS.parent.mkdir(parents=True, exist_ok=True)
        STYLE_COUNTS.write_text(json.dumps(counts, ensure_ascii=False),
                                encoding="utf-8")
    except Exception:
        pass


def style_tendency() -> dict[str, float]:
    """Tendency from an accumulating counter file (bypasses memory dedup).

    Each captured signal adds 0.3 to that dim (capped 0.99), so repeated
    corrections actually accumulate (memory dedup would collapse them).
    """
    counts = _load_counts()
    return {d: round(min(0.99, counts.get(d, 0) * 0.3), 3) for d in STYLE_DIMS}


def active_style_lines(tendencies: dict[str, float]) -> list[str]:
    """Style sentences for persona injection (only when |v| >= threshold)."""
    lines = []
    style_desc = {
        "casual": ("更口语随意些，别端着", "更正式克制些"),
        "concise": ("回应更简短精炼", "可以更展开详尽"),
        "detailed": ("可以更详细展开", "回应更简洁些"),
        "warm": ("语气更暖、更有人情味", "语气更冷静克制"),
        "poetic": ("措辞更有诗意", "措辞更平实直白"),
    }
    for dim, v in tendencies.items():
        if v >= _INJECT_THRESHOLD:
            lines.append(style_desc[dim][0])
        elif v <= -_INJECT_THRESHOLD:
            lines.append(style_desc[dim][1])
    return lines


def capture_style_signal(text: str, memory: Optional[object] = None) -> list[str]:
    """Store style-preference items for any detected signals (best-effort)."""
    signals = detect_style_signals(text)
    if not signals:
        return signals
    _bump_counts(signals)
    if memory is None:
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
