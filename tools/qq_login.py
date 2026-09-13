"""Switch NapCat/QQ quick-login account (ledger 0322).

Usage:
  python tools/qq_login.py 元亨        # quick-login the Yuanheng account
  python tools/qq_login.py 主号        # quick-login the owner's main account
  python tools/qq_login.py 2258374446  # by uin

Saves the chosen account as NapCat ``autoLoginAccount`` (webui.json) and
launches it via ``launcher-user.bat <uin>``. QQNT quick-logs-in if that
account's session was saved before; otherwise scan the QR once.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.yhlz_paths import (  # noqa: E402
    BOT_UIN, MASTER_UIN, NAPCAT_LAUNCHER, NAPCAT_WEBUI, QQWATCH_SHELL,
)

ALIASES = {"元亨": BOT_UIN, "yuanheng": BOT_UIN,
           "主号": MASTER_UIN, "master": MASTER_UIN, "owner": MASTER_UIN,
           "老爹": MASTER_UIN}


def resolve(arg: str) -> str:
    a = str(arg or "").strip()
    if a in ALIASES:
        return ALIASES[a]
    return a if a.isdigit() else ""


def set_auto_account(uin: str) -> bool:
    """Persist the chosen account as NapCat's auto-login account."""
    try:
        d = json.loads(NAPCAT_WEBUI.read_text(encoding="utf-8"))
        d["autoLoginAccount"] = str(uin)
        tmp = NAPCAT_WEBUI.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(NAPCAT_WEBUI)
        return True
    except Exception:
        return False


def switch(uin: str) -> None:
    kill = QQWATCH_SHELL / "KillQQ.bat"
    if kill.exists():
        subprocess.run(["cmd", "/c", str(kill)], cwd=str(QQWATCH_SHELL),
                       capture_output=True)
    subprocess.Popen(["cmd", "/c", str(NAPCAT_LAUNCHER), str(uin)],
                     cwd=str(QQWATCH_SHELL), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    set_only = "--set-only" in sys.argv
    uin = resolve(arg)
    if not uin:
        print("用法: python tools/qq_login.py 元亨|主号|<uin> [--set-only]")
        return 2
    ok = set_auto_account(uin)
    tag = "元亨号" if uin == BOT_UIN else ("老爹主号" if uin == MASTER_UIN else "账号")
    if set_only:
        print(f"autoLoginAccount -> {uin}（{tag}）saved={ok}（未启动）")
        return 0
    switch(uin)
    print(f"已切换快捷登录 -> {uin}（{tag}）；会话未保存过则扫码一次，之后免扫码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
