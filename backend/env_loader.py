"""Minimal .env loader (no third-party dependency) + 代理环境消毒。"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV = _PROJECT_ROOT / ".env"
_loaded = False

# NO_PROXY 里带方括号的 IPv6（如 `[::1]`）会让 httpx 直接抛
# `InvalidURL: Invalid port: ':1]'`——而且是对**每一个**请求（2026-10-13 22:0x
# 事故：从 DSH 会话里重启的 daemon 继承了该值，元亨在 QQ 上全哑）。urllib 不受
# 影响，所以只有 daemon 的 httpx 链路死掉，症状很像"模型挂了"，实则环境变量。
_PROXY_KEYS = ("NO_PROXY", "no_proxy")


def sanitize_proxy_env(env: dict | None = None) -> list[str]:
    """去掉 NO_PROXY 里带方括号的主机项；返回改动说明（便于日志）。

    只清方括号项，其余条目保持顺序并去重；`HTTP_PROXY` 等一律不动。
    """
    target = os.environ if env is None else env
    changes: list[str] = []
    for key in _PROXY_KEYS:
        raw = target.get(key)
        if not raw:
            continue
        parts = [p.strip() for p in str(raw).split(",")]
        kept: list[str] = []
        dropped: list[str] = []
        for part in parts:
            if not part:
                continue
            if part.startswith("[") and part.endswith("]"):
                dropped.append(part)
                continue
            if part not in kept:
                kept.append(part)
        if not dropped:
            continue
        target[key] = ",".join(kept)
        changes.append(f"{key}: 去掉 {dropped}（httpx InvalidURL 隐患）")
    return changes


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
    sanitize_proxy_env()
