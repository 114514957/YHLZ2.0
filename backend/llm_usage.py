# -*- coding: utf-8 -*-
"""LLM 记账与重试（台账 1239）。

老爹定论：**费用不设限，但要有账**。所以这里只统计、不拦截。

记录字段：时间 / 渠道 / 模型 / provider / prompt_tokens / completion_tokens /
        总耗时 / 是否重试过 / 估算费用（可配置单价）
落盘：`cache/llm_usage.jsonl`（> 20000 行轮转）
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

__all__ = ["record", "summary", "PRICES", "llm_call", "LLMUnavailable"]

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parent.parent / "cache" / "llm_usage.jsonl"
_MAX = int(os.getenv("YHLZ_LLM_USAGE_MAX", "20000"))

# 单价（元 / 百万 token）；不确定就按公开牌价填，可被环境变量覆盖。
# 注意：这只是**估算**，对账以服务商账单为准。
PRICES = {
    "deepseek-chat": {
        "in": float(os.getenv("YHLZ_PRICE_IN", "2.0")),
        "out": float(os.getenv("YHLZ_PRICE_OUT", "8.0")),
    },
}


class LLMUnavailable(RuntimeError):
    """云端不可用（重试耗尽）。**明确抛出，不静默降级**——老爹 1231：不做本地兜底。"""


def _rotate(p: Path) -> None:
    try:
        if p.exists() and p.stat().st_size > 8 * 1024 * 1024:
            os.replace(p, p.with_suffix(".jsonl.1"))
    except Exception:  # noqa: BLE001
        pass


def record(*, channel: str = "", model: str = "", provider: str = "",
           prompt_tokens: int = 0, completion_tokens: int = 0,
           seconds: float = 0.0, retries: int = 0, ok: bool = True,
           error: str = "", meta: Optional[dict[str, Any]] = None) -> None:
    price = PRICES.get(model, {})
    cost = ((prompt_tokens or 0) / 1e6 * price.get("in", 0.0)
            + (completion_tokens or 0) / 1e6 * price.get("out", 0.0))
    rec = {
        "ts": round(time.time(), 3),
        "channel": str(channel)[:24],
        "provider": str(provider)[:12],
        "model": str(model)[:32],
        "in": int(prompt_tokens or 0),
        "out": int(completion_tokens or 0),
        "sec": round(float(seconds or 0), 3),
        "retries": int(retries or 0),
        "ok": bool(ok),
        "err": str(error)[:80],
        "cost": round(cost, 6),
    }
    if meta:
        rec["meta"] = {k: meta[k] for k in list(meta)[:6]}
    try:
        with _LOCK:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotate(_PATH)
            with _PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def summary(path: Optional[Path] = None) -> dict[str, Any]:
    """汇总（给工作台用）：今日/累计 调用数、token、估算费用、失败率、P50/P95 延迟。"""
    p = path or _PATH
    if not p.exists():
        return {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "fails": 0,
                "p50": 0.0, "p95": 0.0, "today_cost": 0.0, "today_calls": 0}
    rows = []
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        return {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "fails": 0,
                "p50": 0.0, "p95": 0.0, "today_cost": 0.0, "today_calls": 0}
    lat = sorted(float(r.get("sec") or 0) for r in rows)
    day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    today = [r for r in rows if float(r.get("ts") or 0) >= day0]
    pick = lambda xs, q: (xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0)  # noqa: E731
    return {
        "calls": len(rows),
        "in": sum(int(r.get("in") or 0) for r in rows),
        "out": sum(int(r.get("out") or 0) for r in rows),
        "cost": round(sum(float(r.get("cost") or 0) for r in rows), 4),
        "fails": sum(0 if r.get("ok") else 1 for r in rows),
        "p50": round(pick(lat, 0.50), 3),
        "p95": round(pick(lat, 0.95), 3),
        "today_calls": len(today),
        "today_cost": round(sum(float(r.get("cost") or 0) for r in today), 4),
    }


def llm_call(fn, *, channel: str = "", model: str = "", provider: str = "",
             retries: int = 3, base_delay: float = 0.8, **kw) -> Any:
    """带重试与记账地调用一次模型。fn 必须返回 (payload, seconds)。

    重试策略：指数退避 0.8 → 1.6 → 3.2 秒；**只在异常/5xx 上重试**。
    耗尽后抛 `LLMUnavailable`（明确报错，不悄悄换成本地）。
    """
    last = None
    t0 = time.time()
    for attempt in range(max(1, retries)):
        try:
            payload, sec = fn(**kw)
            usage = (payload or {}).get("usage") or {}
            record(channel=channel, model=model, provider=provider,
                   prompt_tokens=int(usage.get("prompt_tokens") or 0),
                   completion_tokens=int(usage.get("completion_tokens") or 0),
                   seconds=sec, retries=attempt, ok=True)
            return payload
        except Exception as ex:  # noqa: BLE001
            last = ex
            if attempt + 1 < max(1, retries):
                time.sleep(base_delay * (2 ** attempt))
    record(channel=channel, model=model, provider=provider,
           seconds=time.time() - t0, retries=max(0, retries - 1), ok=False,
           error="%s: %s" % (type(last).__name__, last))
    raise LLMUnavailable("模型调用失败（已重试 %d 次）：%s: %s"
                         % (retries, type(last).__name__, last))
