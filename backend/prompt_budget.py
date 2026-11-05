"""Prompt budget for the OpenAI-compatible proxy (F-08, ledger 1104).

`/v1/chat/completions` used to forward client `messages` verbatim to llama.cpp.
A long history (or one huge paste) then blew past the 8192-token window and the
upstream answered `400 exceeds the available context size` — 716 of these were
logged before 2026-11-02.

Budgeting is done in **estimated tokens**, not raw characters: for Chinese text
one character is roughly one token, so a "16k chars" budget would still overflow
an 8192 window. The estimator is deliberately conservative:

    tokens ≈ cjk_chars * 1.1 + other_chars / 4

Trimming rules:

* the newest message always survives (it gets truncated only if it alone is
  bigger than the budget);
* system messages are kept, first one truncated only as a last resort;
* oldest other messages are dropped first.

Pure functions, no I/O, no model calls.
"""
from __future__ import annotations

import os
import re
from typing import Any

DEFAULT_BUDGET_TOKENS = int(os.getenv("YHLZ_PROMPT_BUDGET_TOKENS", "6000"))
TRUNC_MARK = "\n…（超出预算，已截断）"

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(cjk * 1.1 + other / 4) + 1


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content or "")


def total_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(_content_text(m)) for m in messages)


def _truncate_text(text: str, keep_tokens: int) -> str:
    """Trim `text` so its estimated tokens fit `keep_tokens` (keeps a marker)."""
    if keep_tokens <= 0:
        return TRUNC_MARK.strip()
    total = estimate_tokens(text)
    if total <= keep_tokens:
        return text
    # proportional cut, then a shrinking loop for safety
    ratio = keep_tokens / max(1, total)
    keep_chars = max(1, int(len(text) * ratio) - len(TRUNC_MARK))
    cut = text[:keep_chars]
    while cut and estimate_tokens(cut + TRUNC_MARK) > keep_tokens:
        cut = cut[: max(1, int(len(cut) * 0.9))]
    return cut + TRUNC_MARK


def _truncate(message: dict[str, Any], keep_tokens: int) -> dict[str, Any]:
    out = dict(message)
    content = message.get("content")
    if isinstance(content, str):
        out["content"] = _truncate_text(content, keep_tokens)
    elif isinstance(content, list):
        budget_left = keep_tokens
        kept: list[Any] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                piece = _truncate_text(part["text"], budget_left)
                budget_left -= estimate_tokens(piece)
                new_part = dict(part)
                new_part["text"] = piece
                kept.append(new_part)
            else:
                kept.append(part)
            if budget_left <= 0:
                break
        kept.append({"type": "text", "text": TRUNC_MARK.strip()})
        out["content"] = kept
    else:
        out["content"] = _truncate_text(str(content or ""), keep_tokens)
    return out


def fit_messages(
    messages: list[dict[str, Any]], budget_tokens: int | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fit `messages` into `budget_tokens`; returns (fitted, stats)."""
    budget = int(budget_tokens if budget_tokens is not None else DEFAULT_BUDGET_TOKENS)
    if budget <= 0:
        budget = DEFAULT_BUDGET_TOKENS
    msgs = [dict(m) for m in (messages or [])]
    stats: dict[str, Any] = {
        "budget_tokens": budget,
        "original_tokens": total_tokens(msgs),
        "dropped_messages": 0,
        "truncated": False,
    }
    if not msgs or stats["original_tokens"] <= budget:
        stats["fitted_tokens"] = stats["original_tokens"]
        return msgs, stats

    system = [m for m in msgs if m.get("role") == "system"]
    rest = [m for m in msgs if m.get("role") != "system"]
    newest = rest[-1] if rest else None
    pool = rest[:-1] if len(rest) > 1 else []

    def tokens_of(items: list[dict[str, Any]]) -> int:
        return total_tokens(system) + total_tokens(items) + (
            estimate_tokens(_content_text(newest)) if newest else 0)

    while pool and tokens_of(pool) > budget:
        pool.pop(0)
        stats["dropped_messages"] += 1

    kept = system + pool + ([newest] if newest else [])
    current = total_tokens(kept)
    if current > budget:
        over = current - budget
        if newest is not None:
            newest_tokens = estimate_tokens(_content_text(newest))
            if newest_tokens > over:
                kept = system + pool + [_truncate(newest, newest_tokens - over)]
                stats["truncated"] = True
            elif system:
                first_tokens = estimate_tokens(_content_text(system[0]))
                kept[0] = _truncate(system[0], max(1, first_tokens - over))
                stats["truncated"] = True
        elif system:
            first_tokens = estimate_tokens(_content_text(system[0]))
            kept[0] = _truncate(system[0], max(1, first_tokens - over))
            stats["truncated"] = True
    stats["fitted_tokens"] = total_tokens(kept)
    stats["kept_messages"] = len(kept)
    return kept, stats
