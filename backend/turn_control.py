"""Per-channel turn cancellation (P0 #17 优雅停止).

A cooperative cancel flag: the UI requests cancel; the running turn checks it
between tool rounds / during streaming and stops gracefully (keeps what's
produced). Keyed by channel.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_cancel: dict[str, bool] = {}


def request(channel: str = "console") -> None:
    with _lock:
        _cancel[str(channel or "console")] = True


def clear(channel: str = "console") -> None:
    with _lock:
        _cancel[str(channel or "console")] = False


def cancelled(channel: str = "console") -> bool:
    with _lock:
        return bool(_cancel.get(str(channel or "console")))
