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
             "闭嘴", "别说了", "烦", "不满意", "不是这样", "别那样", "停",
             "太长", "说重点", "简洁", "别绕", "绕弯", "程式化", "太客套",
             "废话", "重点呢", "别废话", "听不清", "乱了")
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


def _recent(limit: int = 60) -> list[dict]:
    if not SIGNALS_FILE.exists():
        return []
    out = []
    for ln in SIGNALS_FILE.read_text(encoding="utf-8").splitlines()[-int(limit):]:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


async def suggest(llm_turn, limit: int = 60) -> dict:
    """Stage-2 (ledger 0194/0196): LLM reads recent owner signals and proposes
    small adjustments. Adoption stays manual (owner confirms) — suggestion only.

    Returns {"ok", "signals": n, "suggestions": [...]}
    """
    rows = _recent(limit=limit)
    if len(rows) < 3:
        return {"ok": False, "reason": "信号还太少（当前 %d 条，满 3 条再出建议）" % len(rows)}
    payload = "".join(
        f"[{r['kind']}] {r['text'][:120]}\n" for r in rows)
    sys_p = ("你是元亨的数字神经分析器。阅读老爹近期的反馈信号（praise 表扬/"
             "critique 批评/correction 更正），找重复出现的偏好或问题，产出 1-3 条"
             "**小幅度、可执行**的自我调整建议（说话风格/行为习惯/OCEAN 五维表达）。"
             "输出 JSON：{\"suggestions\": [{\"target\": \"style|behavior|five_dim\", "
             "\"dimension\": \"如 casual/verbose/...或 openness...\", "
             "\"suggestion\": \"一句话具体怎么改(<=80字)\", "
             "\"reason\": \"基于哪几条信号(<=60字)\"}]}。宁少精。")
    resp = await llm_turn([{"role": "user", "content": sys_p + payload}], [])
    import re as _re

    txt = str(resp.get("content") or "")
    m = _re.search(r"\{.*\}", txt, _re.S)
    try:
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}
    return {"ok": True, "signals": len(rows),
            "suggestions": (parsed.get("suggestions") or [])[:3]}
