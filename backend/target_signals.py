"""Digital-nerve signal capture (ledger 0193): record owner feedback signals.

Each signal = one JSONL row {ts, kind(praise|critique|correction), text, channel}.
Future stage-2 (auto-tuning) consumes these; for now they simply accumulate in
data/cognition_signals.jsonl (bounded tail) — nothing auto-adjusts yet.
"""
from __future__ import annotations

import json
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGNALS_FILE = _ROOT / "data" / "cognition_signals.jsonl"
MAX_LINES = 400

_PRAISE = ("好", "很好", "不错", "棒", "厉害", "学到了", "挺好", "对，就是这样",
           "漂亮", "优秀", "满意", "就这样", "可以了", "赞")
_CRITIQUE = ("不对", "错了", "不好", "别这样", "不行", "太差", "啰嗦", "话痨",
             "闭嘴", "别说了", "烦", "不满意", "不是这样", "别那样", "停")
_CORRECTION = ("改主意", "更正", "说错", "之前错", "推翻", "收回", "其实不是", "应该")


def classify_signal(text: str) -> str:
    """kind = praise | critique | correction | ''"""
    if any(w in text for w in _CORRECTION):
        return "correction"
    if any(w in text for w in _PRAISE):
        return "praise"
    if any(w in text for w in _CRITIQUE):
        return "critique"
    return ""


def capture(text: str, channel: str = "private") -> str:
    """Append one signal row if text is a recognizable owner signal."""
    kind = classify_signal(str(text))
    if not kind:
        return ""
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "kind": kind,
           "text": str(text)[:300], "channel": str(channel)[:30]}
    lines = []
    if SIGNALS_FILE.exists():
        try:
            lines = SIGNALS_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
    lines.append(json.dumps(row, ensure_ascii=False))
    del lines[:-MAX_LINES]
    SIGNALS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"signal:{kind}"


def count() -> dict:
    from collections import Counter

    c = Counter()
    if SIGNALS_FILE.exists():
        for ln in SIGNALS_FILE.read_text(encoding="utf-8").splitlines():
            try:
                c[json.loads(ln).get("kind", "?")] += 1
            except Exception:
                pass
    return dict(c)
