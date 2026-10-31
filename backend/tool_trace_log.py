"""真实工具调用留痕（ledger 0873）。

问题：现有 `tool_use_v*.jsonl` 是按 schema **生成**的轨迹，不是元亨真实调用的记录；
      运行时每轮的 `tool_uses` 只在 HTTP 响应里出现一次，没有落盘。
做法：`ConversationSession.run_turn` 结束后把本轮的 tool_uses 追加到
      `data/tool_traces/live.jsonl`，记录：
        channel / user_text / 每个工具 {name, arguments(脱敏截断), ok, error,
        output(截断), readback, elapsed_ms, trace_id} / iterations。
      再经 `tools/v9_tool_traces_build.py` 汇编为训练样本（真实轨迹，非生成）。

隐私：`arguments` 里命中 token/secret/password/key 的键值会被打码；其余连同 output 截断到
      600 字符，避免整段文件内容写进语料。
"""
from __future__ import annotations

import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tool_traces" / "live.jsonl"

SECRET_HINTS = ("token", "secret", "password", "passwd", "api_key", "apikey",
                "authorization", "cookie")
MAX_ARG_CHARS = 600
MAX_OUT_CHARS = 600


def _mask(obj, depth: int = 0):
    if depth > 4:
        return "..."
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(h in str(k).lower() for h in SECRET_HINTS):
                out[k] = "***"
            else:
                out[k] = _mask(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_mask(v, depth + 1) for v in obj[:20]]
    if isinstance(obj, str):
        return obj[:MAX_ARG_CHARS]
    return obj


def _get(u, key, default=None):
    if isinstance(u, dict):
        return u.get(key, default)
    return getattr(u, key, default)


def log_turn(channel: str, user_text: str, tool_uses, *, extra: dict | None = None) -> None:
    """追加一条本轮工具调用记录；任何异常都吞掉（不能影响对话）。"""
    try:
        if not tool_uses:
            return
        items = []
        for u in tool_uses:
            args = _get(u, "arguments") or {}
            items.append({
                "name": str(_get(u, "name") or "?"),
                "arguments": _mask(args),
                "ok": bool(_get(u, "ok")),
                "error": str(_get(u, "error") or "")[:200],
                "output": str(_get(u, "output") or "")[:MAX_OUT_CHARS],
                "readback": str(_get(u, "readback") or "")[:200],
                "elapsed_ms": round(float(_get(u, "elapsed_ms") or 0.0), 1),
            })
        rec = {"ts": time.time(), "channel": str(channel or ""),
               "user_text": str(user_text or "")[:300],
               "tools": items, "generated": False}
        if extra:
            rec.update(extra)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
