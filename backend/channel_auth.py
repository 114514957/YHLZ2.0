"""Channel identity authentication for daemon requests (Step 1).

Validates that a claimed channel is consistent with the caller's source.
Prevents groups from impersonating owner channels (`qq_p*`).

Rules:
- source="console"    → channel must be "console"
- source="qq_bridge"  → channel must match qq_p* or qq_g*
- source="public"     → channel must be "public"
- source missing/unknown → reject (fail-closed)
"""
from __future__ import annotations

import re
from typing import Optional

_VALID_SOURCES = frozenset({"console", "qq_bridge", "public"})
_QQ_P = re.compile(r"^qq_p[0-9]{5,15}$")
_QQ_G = re.compile(r"^qq_g[0-9]{5,15}$")


class ChannelAuthError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code + (f": {detail}" if detail else ""))


def validate_channel(source: str, channel: str) -> str:
    """Return the normalized channel if valid, else raise ChannelAuthError."""
    src = str(source or "").strip()
    ch = str(channel or "").strip()

    if src not in _VALID_SOURCES:
        raise ChannelAuthError("CHANNEL-AUTH-UNKNOWN-SOURCE", src[:80])

    if src == "console":
        if ch not in ("console", "private", "default"):
            raise ChannelAuthError("CHANNEL-AUTH-CONSOLE-CHANNEL", ch[:80])
        return "console"

    if src == "public":
        if ch != "public":
            raise ChannelAuthError("CHANNEL-AUTH-PUBLIC-CHANNEL", ch[:80])
        return "public"

    # src == "qq_bridge"
    if not (_QQ_P.match(ch) or _QQ_G.match(ch)):
        raise ChannelAuthError("CHANNEL-AUTH-BAD-QQ-CHANNEL", ch[:80])
    return ch


def is_owner_channel(channel: str) -> bool:
    """Owner = console or the configured master's exact QQ private channel."""
    from backend.yhlz_paths import MASTER_UIN
    c = str(channel or "").strip()
    return c == "console" or c == f"qq_p{MASTER_UIN}"
