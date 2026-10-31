"""Notification dedupe / rate-limit (F5, ledger 0436; fail-closed + 决策日志, 0496).

Autonomy and consolidation notices used to repeat verbatim every cycle
(the owner saw "任务完成汇报" / "[自主]" noise). Keep a small fingerprint
ledger: identical or near-identical text inside `cooldown` is dropped, and
each kind is capped per 24h window. State: cache/notify_guard.json.

Never raises. Failures now fail **closed**（0496）: 状态读写失败时**丢弃**本条通知，
而不是放行——坏掉的守卫不能再刷屏老爹。`guard_error` 会落进决策日志
（cache/notify_guard_decisions.json）并打一条 stderr 警告；状态文件只是内容损坏
（JSON 解析失败）时按"空账本"处理，可自愈，不算失败。

`allow_ex()` 额外返回拦截原因（ok / duplicate / daily_cap / guard_error），
供自主 tick 记账使用；`allow()` 是只取布尔值的薄封装。
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re
import sys
import time

logger = logging.getLogger(__name__)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE_FILE = _ROOT / "cache" / "notify_guard.json"

DEFAULT_COOLDOWN = 6 * 3600.0
DEFAULT_MAX_PER_DAY = 4
_KEEP = 200
_WINDOW = 72 * 3600.0
_MAX_DECISIONS = 200


def _fp(text: str) -> str:
    norm = re.sub(r"[\s\u3000]+", "", str(text or ""))[:160]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def decisions_file(state_file: pathlib.Path | None = None) -> pathlib.Path:
    """决策日志与状态文件同目录（测试替换 state_file 时自动隔离）。"""
    base = pathlib.Path(state_file) if state_file else STATE_FILE
    return base.parent / "notify_guard_decisions.json"


def _record(state_file: pathlib.Path, entry: dict) -> None:
    """追加一条决策（有界，保留最后 _MAX_DECISIONS 条）。本身绝不抛。"""
    path = decisions_file(state_file)
    try:
        rows: list = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        if not isinstance(rows, list):
            rows = []
        rows.append(entry)
        del rows[:-_MAX_DECISIONS]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — 记录失败不能反过来打断主流程
        logger.warning("notify_guard: 决策日志写入失败: %s", exc)


def allow_ex(kind: str, text: str, cooldown: float = DEFAULT_COOLDOWN,
             max_per_day: int = DEFAULT_MAX_PER_DAY, now: float | None = None,
             state_file: pathlib.Path | None = None) -> tuple[bool, str]:
    """(放行?, 原因)，原因 ∈ ok / duplicate / daily_cap / guard_error。"""
    ts = time.time() if now is None else float(now)
    path = pathlib.Path(state_file) if state_file else STATE_FILE
    fp = _fp(text)
    head = re.sub(r"[\s\u3000]+", " ", str(text or "")).strip()[:80]
    allowed, reason = False, "guard_error"
    try:
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}  # 内容损坏 → 当空账本，可自愈，不当成失败
        if not isinstance(data, dict):
            data = {}
        items = [it for it in (data.get(kind) or [])
                 if isinstance(it, dict)
                 and ts - float(it.get("ts") or 0) < _WINDOW]
        if any(it.get("fp") == fp
               and ts - float(it.get("ts") or 0) < float(cooldown)
               for it in items):
            allowed, reason = False, "duplicate"
        elif int(max_per_day) > 0 and sum(
                1 for it in items
                if float(it.get("ts") or 0) >= ts - 24 * 3600) >= int(max_per_day):
            allowed, reason = False, "daily_cap"
        else:
            items.append({"fp": fp, "ts": ts})
            data[kind] = items[-_KEEP:]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            allowed, reason = True, "ok"
    except Exception as exc:  # noqa: BLE001 — fail-closed（0496）：坏守卫宁可不说话
        allowed, reason = False, "guard_error"
        logger.warning("notify_guard: 状态读写失败，fail-closed 丢弃本条: %s", exc)
        print(f"[notify_guard] fail-closed drop kind={kind}: {exc}",
              file=sys.stderr, flush=True)
    _record(path, {"ts": ts, "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                                  time.localtime(ts)),
                   "kind": str(kind), "reason": reason,
                   "decision": "allow" if allowed else "drop",
                   "fp": fp, "head": head})
    return allowed, reason


def allow(kind: str, text: str, cooldown: float = DEFAULT_COOLDOWN,
          max_per_day: int = DEFAULT_MAX_PER_DAY, now: float | None = None,
          state_file: pathlib.Path | None = None) -> bool:
    """True if this notice may be pushed (and records the decision)."""
    return allow_ex(kind, text, cooldown=cooldown, max_per_day=max_per_day,
                    now=now, state_file=state_file)[0]


def recent(limit: int = 20,
           state_file: pathlib.Path | None = None) -> list[dict]:
    """读取最近 limit 条决策（时间倒序），供 CLI / 工作台审计。只读。"""
    path = decisions_file(state_file)
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    return list(reversed(rows[-max(1, int(limit)):]))