"""DEPRECATED (2026-10-20, ledger 0831): 旧 Full 链的 NapCat 在线看护重启。

旧 ``tools/napcat_watch.py`` 与 Lite 链抢同一个 QQ 号（第二个 WS 消费者、
旧 ``cache/tmp/napcat_status.json``），external 模式下启动器/看门狗会把它收掉；
再手工拉起只会形成"起了又被收"的抖动。

QQ 的掉线与恢复现在由 ``tools/qq_bridge_watchdog.py`` 负责。要看状态：
    .venv\\Scripts\\python.exe -B tools\\qq_bridge_control.py status --profile lite

Usage: python tools/napcat_watch_restart.py   (仅打印退役说明)
"""
from __future__ import annotations

import sys

MESSAGE = """[napcat_watch_restart] 已退役（0831）。
旧 napcat_watch 不再维护 QQ 在线状态；Lite 看门狗负责掉线恢复。
查看状态：.venv\\Scripts\\python.exe -B tools\\qq_bridge_control.py status --profile lite
"""


def main() -> int:
    print(MESSAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
