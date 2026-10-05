"""T3（R3, ledger 0629）：统一发送适配器——普通回复 / 主动 outbox / 通知**共用**同一持久投递。

链路：`qq_delivery_store.enqueue`（幂等）→ `claim_by_id`（租约 epoch）→ `transport`
→ 成功 `mark_confirmed`；明确拒绝 `mark_rejected`；**发送前失败 → retryable（有限退避重试）**；
**发送后失败/超时/丢 ack → unknown（不重发）**。

- `transport(action, params)` 为**注入点**：生产接 OneBot；测试接假传输。
- 本模块只编排；状态与事务在 `qq_delivery_store`。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import backend.qq_delivery_store as ds
from backend.qq_delivery import DeliveryTransportError, classify_response


async def _default_transport(action: str, params: dict) -> dict:
    return {"status": "ok", "retcode": 0}


async def send(con, *, source_event_id: str, channel: str, target_type: str, target_id: str,
               kind: str = "reply", action: str = "send_msg", params: dict | None = None,
               payload_ref: str = "", payload_hash: str = "",
               transport: Callable[[str, dict], Awaitable[dict]] | None = None,
               owner: str = "adapter", now: float | None = None, lease_s: float = 90.0,
               max_retries: int = 2, backoff: tuple[float, ...] = (0.0,)) -> dict:
    """一次逻辑发送（幂等 + 租约 + 明确效果状态）；返回脱敏终态。"""
    now = time.time() if now is None else now
    params = dict(params or {})
    enq = ds.enqueue(con, source_event_id=source_event_id, channel=channel,
                     target_type=target_type, target_id=target_id, kind=kind,
                     payload_ref=payload_ref, payload_hash=payload_hash, now=now)
    did = enq["delivery_id"]
    if enq["idempotent"] and enq["state"] in ("confirmed", "unknown", "expired", "rejected"):
        return {"delivery_id": did, "state": enq["state"], "idempotent": True, "attempts": 0}
    claimed = ds.claim_by_id(con, did, owner, now=now, lease_s=lease_s)
    if not claimed:
        return {"delivery_id": did, "state": "not_claimable",
                "idempotent": enq["idempotent"], "attempts": 0}
    ep = claimed["lease_epoch"]
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = await (transport(action, params) if transport
                          else _default_transport(action, params))
        except DeliveryTransportError as exc:
            stage = getattr(exc, "stage", "after_send")
            if stage == "before_send" and attempts <= max_retries:
                delay = backoff[min(attempts - 1, len(backoff) - 1)] if backoff else 0.0
                if delay:
                    await asyncio.sleep(delay)
                continue
            st = ds.mark_failed(con, did, lease_epoch=ep,
                                before_send=(stage == "before_send"),
                                error_code=type(exc).__name__)
            return {"delivery_id": did, "state": st, "attempts": attempts}
        status, error_type = classify_response(resp)
        if status == "confirmed":
            ds.mark_confirmed(con, did, lease_epoch=ep, ack_ref=str(resp.get("retcode", "")))
            return {"delivery_id": did, "state": "confirmed", "attempts": attempts}
        if status == "rejected":
            ds.mark_rejected(con, did, lease_epoch=ep, error_code=error_type)
            return {"delivery_id": did, "state": "rejected", "attempts": attempts}
        ds.mark_failed(con, did, lease_epoch=ep, before_send=False, error_code=error_type)
        return {"delivery_id": did, "state": "unknown", "attempts": attempts}
