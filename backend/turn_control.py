"""Per-channel turn cancellation (P0 #17 优雅停止).

A cooperative cancel flag: the UI requests cancel; the running turn checks it
between tool rounds / during streaming and stops gracefully (keeps what's
produced). Keyed by channel.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_cancel: dict[str, bool] = {}
_generation: dict[str, int] = {}


def request(channel: str = "console") -> None:
    with _lock:
        _cancel[str(channel or "console")] = True


def clear(channel: str = "console") -> int:
    """Begin a generation; an old turn can never be uncancelled by a new one."""
    key = str(channel or "console")
    with _lock:
        _cancel[key] = False
        _generation[key] = _generation.get(key, 0) + 1
        return _generation[key]


def cancelled(channel: str = "console", generation: int | None = None) -> bool:
    key = str(channel or "console")
    with _lock:
        return (bool(_cancel.get(key)) or
                (generation is not None and generation != _generation.get(key, 0)))
