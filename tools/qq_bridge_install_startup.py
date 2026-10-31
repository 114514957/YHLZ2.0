"""DEPRECATED (2026-10-20, ledger 0830): 旧的「只装 Lite 自启」迁移工具。

它会给启动目录再加一条 ``YHLZ-QQ桥Lite.lnk``。现在开机自启只有一条：
``YH 开机自启.lnk`` → ``YH_boot.bat``（服务栈 → 看门狗 → QQ Lite），由
``tools/yhlz_boot_startup.py`` 统一安装/回滚。这里保留同名命令只为兼容
老文档/老习惯，实际动作全部转发过去，避免又出现「新旧两条都在启动」。

Usage:
    python tools/qq_bridge_install_startup.py            # dry-run
    python tools/qq_bridge_install_startup.py --apply
    python tools/qq_bridge_install_startup.py --rollback
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--state-dir", default=None)  # 旧参数，忽略
    ap.add_argument("-h", "--help", action="store_true")
    args, _unknown = ap.parse_known_args(argv)
    if args.help:
        print(__doc__)
        return 0
    print("[qq_bridge_install_startup] 已并入 yhlz_boot_startup.py（0830）："
          "开机自启只有一条 YH 开机自启 → YH_boot.bat", flush=True)
    import yhlz_boot_startup as boot

    forwarded = (["--apply"] if args.apply else
                 ["--rollback"] if args.rollback else [])
    return boot.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
