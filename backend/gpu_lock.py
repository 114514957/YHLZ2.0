"""GPU task interlock (ledger 0459): singing vs chat/TTS must not overlap.

The 8GB card cannot hold the LLM (~4.5GB) + Qwen-TTS clone (~2.4GB) + SoulX
SVC (~7.4GB) at once. Operator decision: hard interlock — only one side runs.

States owned here:
  ""          idle
  "sing-prep"  cover preprocessing (vocal separation / F0) — chat MAY run
  "sing-svc"   SVC window — chat/TTS are REFUSED until released

Chat turns register via chat_enter/chat_exit so the job can wait for them to
drain before starting the SVC window (never kill an in-flight turn).
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_state = {"owner": "", "since": 0.0, "chat": 0}


def owner() -> str:
    with _lock:
        return _state["owner"]


def acquire_sing() -> bool:
    """Begin a cover job (prep state). Fails if another job owns the GPU."""
    with _lock:
        if _state["owner"].startswith("sing"):
            return False
        _state["owner"] = "sing-prep"
        _state["since"] = time.time()
        return True


def enter_window() -> bool:
    """Upgrade to the SVC window state (chat/TTS blocked afterwards)."""
    with _lock:
        if _state["owner"] != "sing-prep":
            return False
        _state["owner"] = "sing-svc"
        _state["since"] = time.time()
        return True


def release_sing() -> None:
    with _lock:
        if _state["owner"].startswith("sing"):
            _state["owner"] = ""
            _state["since"] = 0.0


def chat_blocked() -> bool:
    with _lock:
        return _state["owner"] == "sing-svc"


def chat_enter() -> bool:
    """True if a chat/TTS call may run now."""
    with _lock:
        if _state["owner"] == "sing-svc":
            return False
        _state["chat"] += 1
        return True


def chat_exit() -> None:
    with _lock:
        _state["chat"] = max(0, _state["chat"] - 1)


def chat_active() -> int:
    with _lock:
        return _state["chat"]


def wait_chat_idle(timeout: float = 120.0) -> bool:
    """Wait (never kills an in-flight turn) until chat is idle."""
    t0 = time.time()
    while chat_active() > 0 and time.time() - t0 < timeout:
        time.sleep(1)
    return chat_active() == 0


def busy_message() -> str:
    with _lock:
        secs = int(time.time() - _state["since"]) if _state["since"] else 0
    return (f"（元亨正在唱歌，GPU 被占用约 {max(1, secs // 60 + 1)} 分钟了；"
            "唱完再聊，稍等一下~）")
