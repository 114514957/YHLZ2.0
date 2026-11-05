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

# 2026-11-05（台账 1103）：测试期临时目录重定向。
# 113 个测试用 tempfile.mkdtemp()（不带 dir=），会把 tmp* 扔进当前目录=仓库根。
# 只在 unittest 已导入时生效，生产进程不受影响；根目录从此不再长临时目录。
try:
    import sys as _sys

    if "unittest" in _sys.modules:
        import tempfile as _tempfile
        from pathlib import Path as _Path

        _tmp_root = _Path(__file__).resolve().parent.parent / "cache" / "tmp"
        _tmp_root.mkdir(parents=True, exist_ok=True)
        _tempfile.tempdir = str(_tmp_root)
except Exception:
    pass
