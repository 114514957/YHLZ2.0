# -*- coding: utf-8 -*-
"""群聊发送节流：防止触发 QQ 的 retcode 1200（发送被限制）。

背景（2026-11-16）：
  · 群里每来一条她都接 → 22:14–22:15 连续 6 条 → QQ 回 `retcode 1200`，全部发不出去；
  · 日志：`EventChecker Failed: NodeIKernelMsgService/sendMsg`，投递状态 `rejected`。

规则（可在 cache/qq_throttle.json 调）：
  · 群聊普通：两次回复间隔 ≥ 25 秒
  · 群聊被 @：≥ 8 秒（老爹叫她，得应）
  · 私聊：≥ 5 秒
超时就**不产生回复**（连模型都不调，省钱也省限流）。
"""
from __future__ import annotations

import io
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "cache", "qq_throttle.json")
DEFAULTS = {"group_gap": 25.0, "group_at_gap": 8.0, "private_gap": 5.0}

__all__ = ["allow", "note_sent", "cfg"]


def cfg() -> dict:
    d = dict(DEFAULTS)
    try:
        with io.open(STATE, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw.get("limits"), dict):
            d.update({k: float(v) for k, v in raw["limits"].items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001
        pass
    return d


def _load() -> dict:
    try:
        with io.open(STATE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with io.open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def allow(channel: str, text: str = "") -> tuple[bool, float]:
    """返回 (是否允许回复, 还需等多少秒)。"""
    ch = str(channel or "")
    now = time.time()
    c = cfg()
    if ch.startswith("qq_g"):
        gap = c["group_at_gap"] if "[[at:" in str(text or "") else c["group_gap"]
    elif ch.startswith("qq_p"):
        gap = c["private_gap"]
    else:
        return True, 0.0
    last = float(_load().get(ch) or 0.0)
    wait = gap - (now - last)
    return (wait <= 0), max(0.0, wait)


def note_sent(channel: str) -> None:
    d = _load()
    d[str(channel or "")] = time.time()
    _save(d)
