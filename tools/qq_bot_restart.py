"""DEPRECATED (2026-10-20, ledger 0830): 旧 Full 链的「重启 QQ 桥」入口。

现在 QQ 归 **QQ Bridge Lite** 独占（config/qq_management.json = external）。
这个脚本不再杀进程、不再拉起 ``tools/qq_bot.py``——拉起旧桥会和 Lite 桥抢
同一个 QQ 号，正是「新旧都启动了」的来源。它只把调用转发给官方控制脚本
（等价于工作台里的「重启 QQ 桥」，默认不动 NapCat 登录）。

Usage: python tools/qq_bot_restart.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CONTROL = _ROOT / "tools" / "qq_bridge_control.py"
CONFIG = _ROOT / "config" / "qq_bridge_lite.json"


def main() -> int:
    print("[qq_bot_restart] 已退役（0830）：转发到 QQ Bridge Lite control restart")
    cmd = [sys.executable, "-B", str(CONTROL), "restart", "--profile", "lite",
           "--config", str(CONFIG), "--no-napcat"]
    proc = subprocess.run(cmd, cwd=str(_ROOT))
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
