"""Shared OneBot WebSocket keepalive and connection diagnostics.

This module deliberately knows nothing about QQ message contents.  It only
provides protocol-level ping/pong handling and a redacted, process-local
connection snapshot so a bridge can distinguish an alive process from an alive
socket.  It is safe to use with the ``websockets`` 14/15 client and with small
fake transports in unit tests.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ConnectionSnapshot:
    state: str = "starting"
    connected_at: float = 0.0
    last_rx_at: float = 0.0
    last_tx_at: float = 0.0
    last_ping_at: float = 0.0
    last_pong_at: float = 0.0
    last_error: str = ""
    reconnect_count: int = 0
    heartbeat_failures: int = 0
    next_retry_at: float = 0.0
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, Any]:
        # Timestamps are intentionally numeric and contain no token/message.
        return {
            "state": self.state,
            "connected_at": self.connected_at,
            "last_rx_at": self.last_rx_at,
            "last_tx_at": self.last_tx_at,
            "last_ping_at": self.last_ping_at,
            "last_pong_at": self.last_pong_at,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
            "heartbeat_failures": self.heartbeat_failures,
            "next_retry_at": self.next_retry_at,
            **self._extra,
        }


async def ping_once(ws: Any, state: ConnectionSnapshot, timeout: float) -> None:
    """Send one protocol ping and require its pong within ``timeout``."""
    state.last_ping_at = time.time()
    waiter = ws.ping()
    deadline = max(0.1, timeout)
    # websockets 14/15 returns an awaitable which resolves to a Future; small
    # fakes often return the Future directly.  Apply the timeout to both
    # stages—never await a raw Future before wait_for.
    if isinstance(waiter, asyncio.Future):
        pong = waiter
    elif hasattr(waiter, "__await__"):
        pong = await asyncio.wait_for(waiter, timeout=deadline)
    else:
        pong = waiter
    if pong is not None:
        await asyncio.wait_for(pong, timeout=deadline)
    state.last_pong_at = time.time()
    state.heartbeat_failures = 0


async def heartbeat_loop(
    ws: Any,
    state: ConnectionSnapshot,
    *,
    interval: float,
    timeout: float,
    on_state: Callable[[str], Awaitable[None] | None] | None = None,
) -> None:
    """Keep a OneBot WebSocket alive until cancelled or a ping fails.

    The caller owns reconnect policy.  A failed pong raises ``ConnectionError``
    so the reader/runner can tear down the old socket instead of leaving a
    dead receive loop behind.
    """
    interval = max(1.0, float(interval))
    timeout = max(0.1, float(timeout))
    while True:
        await asyncio.sleep(interval)
        try:
            await ping_once(ws, state, timeout)
            if state.state != "connected":
                state.state = "connected"
                if on_state:
                    result = on_state("connected")
                    if result is not None:
                        await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            state.heartbeat_failures += 1
            state.last_error = type(exc).__name__
            state.state = "degraded"
            if on_state:
                result = on_state("degraded")
                if result is not None:
                    await result
            raise ConnectionError("QQ websocket heartbeat failed") from exc


def websocket_options(*, open_timeout: float = 10.0) -> dict[str, Any]:
    """Stable client options; disable library ping because we own diagnostics."""
    return {
        "open_timeout": max(1.0, float(open_timeout)),
        "close_timeout": 5,
        "ping_interval": None,
        "ping_timeout": None,
        "max_queue": 128,
    }
