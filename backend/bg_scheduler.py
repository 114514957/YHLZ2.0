"""T5（R3, ledger 0613）：统一后台推理协调入口。

设计要点（映射 R4-E / R5）：
- **采集与推理分离**：入站消息只落盘；一切后台 LLM（QQ 抽取/摘要/实体/反思/技能学习）
  统一经本入口排队，不各自直连模型。
- **单活动本地推理 + 前台优先**：有前台在跑/在等时不启动新的后台推理；
  后台拿到名额后再**复核训练/资源策略**（不把"策略标记"当"真实训练观测"）。
- **可观测**：记录每个后台请求的 `kind/endpoint/wait_ms/run_ms/status`（有界），
  供诊断"哪个后台在占用 8GB"。
- 本模块**不持 SQLite 写锁**（只做调度与计时）。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable

_sem: asyncio.Semaphore | None = None
_fg: int = 0
_recent: deque = deque(maxlen=200)
_counters = {"started": 0, "done": 0, "timeout": 0, "error": 0, "skipped_policy": 0}


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)
    return _sem


def foreground_enter() -> None:
    global _fg
    _fg += 1


def foreground_exit() -> None:
    global _fg
    _fg = max(0, _fg - 1)


def foreground_active() -> bool:
    return _fg > 0


async def run(fn: Callable[[], Awaitable[Any]], *, kind: str = "background",
              endpoint: str = "", timeout_s: float = 15.0,
              policy_check: Callable[[], bool] | None = None,
              poll_s: float = 0.01) -> dict:
    """统一后台推理入口。返回 {ok,status,result,wait_ms,run_ms}。"""
    t0 = time.perf_counter()
    # 前台优先：有前台活动时让路（不启动新后台）
    while _fg > 0:
        await asyncio.sleep(poll_s)
    sem = _semaphore()
    async with sem:
        wait_ms = round((time.perf_counter() - t0) * 1000, 1)
        if policy_check is not None and not policy_check():
            _counters["skipped_policy"] += 1
            _recent.append({"kind": kind, "endpoint": endpoint,
                            "status": "skipped_policy", "wait_ms": wait_ms})
            return {"ok": False, "status": "skipped_policy", "result": None,
                    "wait_ms": wait_ms, "run_ms": 0.0}
        _counters["started"] += 1
        t1 = time.perf_counter()
        out: Any = None
        try:
            out = await asyncio.wait_for(fn(), timeout=timeout_s)
            status = "done"
            _counters["done"] += 1
        except asyncio.TimeoutError:
            status = "timeout"
            _counters["timeout"] += 1
        except Exception:  # noqa: BLE001
            status = "error"
            _counters["error"] += 1
        run_ms = round((time.perf_counter() - t1) * 1000, 1)
        _recent.append({"kind": kind, "endpoint": endpoint, "status": status,
                        "wait_ms": wait_ms, "run_ms": run_ms})
        return {"ok": status == "done", "status": status, "result": out,
                "wait_ms": wait_ms, "run_ms": run_ms}


def status() -> dict:
    return {"foreground_active": _fg, "counters": dict(_counters),
            "active": 1 if (_sem is not None and _sem.locked()) else 0,
            "recent": list(_recent)[-20:]}


def reset_for_tests() -> None:
    global _sem, _fg
    _sem = None
    _fg = 0
    _recent.clear()
    for k in _counters:
        _counters[k] = 0
