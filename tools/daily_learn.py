# -*- coding: utf-8 -*-
"""每日学习：跑「说话风格学习」+「群观察入库」，产出一份日报。

老爹 2026-11-16 定的方向：**学习主要目标就是完善人格和说话风格**。
所以每天固定做两件事：
  1. `style_learn.py`：统计她自己的群发言（长度/破折号/反问/@人/被点名），
     产出 `docs/风格/群聊风格学习_<日期>.md`
  2. `group_learn.py --apply`：把群观察/话题/人物写进知识库（供群里用，不进她的个人记忆）

用法：
    python tools\\daily_learn.py            # 跑一遍
    python tools\\daily_learn.py --dry      # 只看会做什么

计划任务：`YH-Daily-Learn`，每天 04:30（见 tools/install_daily_learn.py）
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = sys.executable
LOG = os.path.join(ROOT, "cache", "logs", "daily_learn.log")


def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def run(script: str, args: list[str], timeout: int = 300) -> tuple[bool, str]:
    p = os.path.join(ROOT, "tools", script)
    if not os.path.exists(p):
        return False, "缺少 %s" % script
    r = subprocess.run([PY, "-X", "utf8", p] + args, cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out[-1200:]


def main() -> int:
    dry = "--dry" in sys.argv
    if dry:
        print("会执行：style_learn.py（只统计，不写库）、group_learn.py --apply")
        return 0

    log("=== 每日学习开始 ===")
    ok1, out1 = run("style_learn.py", ["--apply"])
    log("风格学习：%s" % ("成功" if ok1 else "失败"))
    for ln in [x for x in out1.splitlines() if x.strip()][-6:]:
        log("  " + ln.strip()[:110])

    ok2, out2 = run("group_learn.py", ["--apply"])
    log("群观察入库：%s" % ("成功" if ok2 else "失败"))
    for ln in [x for x in out2.splitlines() if x.strip()][-4:]:
        log("  " + ln.strip()[:110])

    log("=== 结束（%s）===" % ("全部成功" if ok1 and ok2 else "有失败项"))
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
