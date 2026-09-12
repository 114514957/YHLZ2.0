"""QQ OneBot access-token lookup (no plaintext in tracked source).

Resolution order:
  1. env `YHLZ_QQ_TOKEN`
  2. config/qqwatch.local.json  (untracked, holds the real token)
  3. config/qqwatch.json        (tracked, token kept empty)

The live bridge (tools/qq_bot.py) reads the token from NapCat's own
onebot11_*.json instead; this helper is for the watcher/probe/qqwatcher.
"""
from __future__ import annotations

import json
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LOCAL = _ROOT / "config" / "qqwatch.local.json"
_BASE = _ROOT / "config" / "qqwatch.json"


def get_token() -> str:
    tok = str(os.getenv("YHLZ_QQ_TOKEN", "") or "").strip()
    if tok:
        return tok
    for f in (_LOCAL, _BASE):
        try:
            v = str(json.loads(f.read_text(encoding="utf-8")).get("token", "") or "")
            if v:
                return v
        except Exception:
            continue
    return ""


def ws_url(host: str = "127.0.0.1", port: int = 3001) -> str:
    url = f"ws://{host}:{port}"
    tok = get_token()
    return url + (f"?access_token={tok}" if tok else "")
