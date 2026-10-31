"""Profile-scoped state paths for the QQ bridge (P0, 2026-10-06).

Resolution priority (guide section 4):
    YHLZ_QQ_STATE_DIR (explicit dir)
    > YHLZ_QQ_PROFILE != "full"  -> <repo>/cache/qq_bridge/<profile>/
    > legacy Full paths          -> <repo>/cache/tmp/ etc.

With no environment set every path is byte-for-byte the old Full path.
Pure path math: no network, no side effects, and never imports the Full
launcher/watchdog.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEGACY_DIR = ROOT / "cache" / "tmp"
STATE_DIR_ENV = "YHLZ_QQ_STATE_DIR"
PROFILE_ENV = "YHLZ_QQ_PROFILE"


def _safe_profile(raw: str) -> str:
    cleaned = "".join(c for c in str(raw or "") if c.isalnum() or c in "-_")
    return cleaned or "full"


def profile() -> str:
    return _safe_profile(os.getenv(PROFILE_ENV, "").strip())


def is_scoped() -> bool:
    return bool(os.getenv(STATE_DIR_ENV, "").strip()) or profile() != "full"


def state_dir() -> pathlib.Path:
    env = os.getenv(STATE_DIR_ENV, "").strip()
    if env:
        return pathlib.Path(env)
    p = profile()
    if p != "full":
        return ROOT / "cache" / "qq_bridge" / p
    return LEGACY_DIR


def path(name: str, legacy: pathlib.Path) -> pathlib.Path:
    """Scoped ``state_dir()/name`` when scoped, else the legacy path."""
    return state_dir() / name if is_scoped() else legacy
