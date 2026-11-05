"""
YHLZ 2.0 Backend Package
"""

__version__ = "2.0.0"
__author__ = "YHLZ Team"

# 2026-11-05（台账 1096）：导入即做代理环境消毒。
# 有些启动器（DSH）会往 NO_PROXY 里注入带方括号的 IPv6 项（如 `[::1]`），
# httpx 0.28 解析它会抛 InvalidURL——不是某一次请求，是**每一个**请求
# （2026-10-13 事故，台账 0815：从 DSH 会话重启的 daemon 元亨 QQ 全哑）。
# launcher 已经给 daemon 消毒；放在这里，任何 import backend 的工具/测试
# 都自动获得同样的保护，避免“环境坏了”被误判成“项目坏了”。
import os as _os

_ENV_CHANGES: list[str] = []
if str(_os.getenv("YHLZ_SKIP_ENV_SANITIZE", "")).strip().lower() not in (
        "1", "true", "yes", "on"):
    try:
        from backend.env_loader import sanitize_proxy_env as _sanitize_proxy_env

        _ENV_CHANGES = _sanitize_proxy_env()
    except Exception:
        _ENV_CHANGES = []
