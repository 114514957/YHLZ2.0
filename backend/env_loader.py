"""Minimal .env loader (no third-party dependency)."""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV = _PROJECT_ROOT / ".env"
_loaded = False


def load_env_file(path: Path = _DEFAULT_ENV) -> bool:
    """Load KEY=VALUE lines from ``path`` into os.environ (no override).

    Returns True when the file was parsed.  Missing/empty lines and comments
    are ignored; existing environment variables always win.
    """
    global _loaded
    if not Path(path).exists():
        return False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    if path == _DEFAULT_ENV:
        _loaded = True
    return True


def ensure_env_loaded() -> None:
    if not _loaded:
        load_env_file()
