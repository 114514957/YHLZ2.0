"""QQ outbound delivery manager (Phase 2: ack / bounded retry / no blind resend).

Plan: ``desktop/QQ桥下一阶段计划书_20260929.md`` (ledger 0528).  Ordinary replies
used to be fire-and-forget, so the bridge could not tell "sent" from "maybe
sent".  This module gives every outbound message exactly one state and enforces
the plan's safety rule: **a response that could not be observed is ``unknown``
and is never blindly resent** (NapCat may have executed it while the response
was lost — resetting would duplicate the QQ message).

States: queued / sending / confirmed / rejected / retryable / unknown / expired.

* ``confirmed`` — OneBot ``status=ok`` and ``retcode=0``.
* ``rejected``  — OneBot answered but refused (params/permission/target).
* ``retryable`` — the connection failed **before** the send was submitted.
* ``unknown``   — the socket died or the ack timed out **after** submission.
* ``expired``   — a reply past its TTL; the send action is dropped.

Only ``retryable`` is retried, at most ``max_retries`` times (backoff 1s/3s).
This module is transport-agnostic and knows nothing about QQ message contents:
it records only a ``payload_hash``, status, timing and error type.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from backend.qq_bridge_state import path as _bridge_path

__all__ = [
    "DELIVERY_STATES",
    "Delivery",
    "DeliveryManager",
    "DeliveryTransportError",
    "classify_response",
]

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = _bridge_path(
    "delivery_status.json", _ROOT / "cache" / "tmp" / "qq_delivery_status.json")

DELIVERY_STATES = (
    "queued", "sending", "confirmed", "rejected",
    "retryable", "unknown", "expired",
)

_COUNTER_KEYS = (
    "qq_delivery_total",
    "qq_delivery_confirmed",
    "qq_delivery_rejected",
    "qq_delivery_retryable",
    "qq_delivery_unknown",
    "qq_delivery_expired",
    "qq_delivery_retry_attempts",
)


class DeliveryTransportError(Exception):
    """Transport failure with an explicit submission stage.

    ``stage='before_send'`` means the request was never submitted → safe to
    retry.  ``stage='after_send'`` means it may already have executed → the
    manager must not blindly resend.
    """

    def __init__(self, message: str = "", *, stage: str = "after_send") -> None:
        super().__init__(str(message))
        self.stage = stage if stage in ("before_send", "after_send") else "after_send"


def classify_response(response: Any) -> tuple[str, str]:
    """Map a OneBot response to ``(status, error_type)`` (see plan §4.2)."""
    if not isinstance(response, dict):
        return "rejected", "malformed_response"
    status = str(response.get("status", "")).lower()
    retcode = response.get("retcode", None)
    ok_code = retcode in (0, None, "0")
    if status == "ok" and ok_code:
        return "confirmed", ""
    if status == "ok":
        return "rejected", f"retcode_{retcode}"
    err = f"status_{status or 'failed'}"
    if retcode is not None:
        err += f"_retcode_{retcode}"
    return "rejected", err


def _hash_payload(params: Any) -> str:
    try:
        body = json.dumps(params, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    except Exception:
        body = repr(params)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


@dataclass
class Delivery:
    delivery_id: str
    kind: str
    target: dict
    payload_hash: str
    status: str = "queued"
    attempt: int = 0
    created_at: float = 0.0
    last_attempt_at: float = 0.0
    expires_at: float = 0.0
    last_error: str = ""
    error_type: str = ""
    reconnected: bool = False

    def redacted(self) -> dict:
        """State only — never the message body."""
        return {
            "delivery_id": self.delivery_id,
            "kind": self.kind,
            "target_type": str(self.target.get("message_type", ""))[:16],
            "payload_hash": self.payload_hash,
            "status": self.status,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "last_attempt_at": self.last_attempt_at,
            "expires_at": self.expires_at,
            "error_type": self.error_type,
            "reconnected": self.reconnected,
        }


class DeliveryManager:
    """Serial (concurrency=1) outbound delivery with explicit states."""

    def __init__(
        self,
        request: Callable[[str, dict], Any],
        *,
        clock: Callable[[], float] = time.time,
        sleep: Optional[Callable[[float], Any]] = None,
        max_retries: int = 2,
        backoff: tuple[float, ...] = (1.0, 3.0),
        reply_ttl_s: float = 30.0,
        status_path: Optional[pathlib.Path] = DEFAULT_STATUS_PATH,
        recent_limit: int = 20,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._request = request
        self._clock = clock
        self._sleep = sleep
        self.max_retries = int(max_retries)
        self.backoff = tuple(float(b) for b in backoff) or (1.0,)
        self.reply_ttl_s = float(reply_ttl_s)
        self.status_path = pathlib.Path(status_path) if status_path else None
        self._lock = threading.RLock()
        self._send_lock: Optional[asyncio.Lock] = None
        self._counters: dict[str, int] = {k: 0 for k in _COUNTER_KEYS}
        self._recent: deque[dict] = deque(maxlen=max(1, int(recent_limit)))
        self._delivery_ids: set[str] = set()

    # ---- observability ---------------------------------------------------
    def counters(self) -> dict:
        with self._lock:
            return dict(self._counters)

    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._recent)

    def snapshot(self) -> dict:
        with self._lock:
            return {"counters": dict(self._counters),
                    "recent": list(self._recent)}

    def _count(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[key] = int(self._counters.get(key, 0)) + int(n)

    def _record(self, d: Delivery) -> None:
        with self._lock:
            self._recent.append(d.redacted())
        if self.status_path is not None:
            try:
                self.status_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.status_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.snapshot(), ensure_ascii=False,
                                          indent=2), encoding="utf-8")
                tmp.replace(self.status_path)
            except Exception:
                pass

    # ---- send ------------------------------------------------------------
    def _guard(self) -> asyncio.Lock:
        if self._send_lock is None:
            self._send_lock = asyncio.Lock()
        return self._send_lock

    def _backoff_for(self, attempt: int) -> float:
        idx = max(0, attempt - 1)
        return self.backoff[idx] if idx < len(self.backoff) else self.backoff[-1]

    async def _do_sleep(self, seconds: float) -> None:
        if self._sleep is not None:
            result = self._sleep(seconds)
            if asyncio.iscoroutine(result):
                await result
            return
        await asyncio.sleep(seconds)

    def _new_id(self) -> str:
        while True:
            candidate = "d_" + uuid.uuid4().hex[:16]
            with self._lock:
                if candidate not in self._delivery_ids:
                    self._delivery_ids.add(candidate)
                    return candidate

    async def send(
        self,
        *,
        kind: str,
        target: dict,
        params: dict,
        action: str = "send_msg",
        payload_hash: str = "",
        ttl_s: Optional[float] = None,
        timeout_s: float = 15.0,
    ) -> dict:
        """Send one logical message; return its redacted terminal record.

        Ordering: sends are serialised (global concurrency 1) so two messages
        to the same target keep their enqueue order (plan §4.4).
        """
        now = self._clock()
        ttl = self.reply_ttl_s if (ttl_s is None and kind == "reply") else ttl_s
        delivery = Delivery(
            delivery_id=self._new_id(),
            kind=str(kind),
            target=dict(target or {}),
            payload_hash=payload_hash or _hash_payload(params),
            status="queued",
            created_at=now,
            expires_at=(now + float(ttl)) if ttl else 0.0,
        )
        self._count("qq_delivery_total")
        async with self._guard():
            return await self._run(delivery, action, params, timeout_s)

    async def _run(self, d: Delivery, action: str, params: dict,
                   timeout_s: float) -> dict:
        retried_marked = False
        while True:
            if d.expires_at and self._clock() > d.expires_at:
                d.status = "expired"
                self._count("qq_delivery_expired")
                self._record(d)
                return d.redacted()
            d.attempt += 1
            d.status = "sending"
            d.last_attempt_at = self._clock()
            try:
                response = self._request(action, params)
                if asyncio.iscoroutine(response):
                    response = await asyncio.wait_for(response, timeout=timeout_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                stage = getattr(exc, "stage", "after_send")
                d.error_type = type(exc).__name__
                d.last_error = str(exc)[:120]
                if stage == "before_send":
                    d.status = "retryable"
                    if not retried_marked:
                        self._count("qq_delivery_retryable")
                        retried_marked = True
                    not_expired = not (d.expires_at and self._clock() > d.expires_at)
                    if d.attempt <= self.max_retries and not_expired:
                        self._count("qq_delivery_retry_attempts")
                        await self._do_sleep(self._backoff_for(d.attempt))
                        continue
                    self._record(d)
                    return d.redacted()
                d.status = "unknown"
                self._count("qq_delivery_unknown")
                self._record(d)
                return d.redacted()
            status, error_type = classify_response(response)
            d.status = status
            d.error_type = error_type
            self._count(f"qq_delivery_{status}"
                        if status in ("confirmed", "rejected")
                        else "qq_delivery_rejected")
            self._record(d)
            return d.redacted()
