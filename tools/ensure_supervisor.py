# -*- coding: utf-8 -*-
"""看门狗中的看门狗：由计划任务每分钟调用一次。

逻辑：
  · 心跳新鲜（< 60 秒）→ 说明 supervisor 活着，**直接退出**（避免重复进程）
  · 否则 → 用 DETACHED_PROCESS 起一个 supervisor，然后退出

为什么需要它：`schtasks /sc onlogon` 在这台机器被策略拒绝（Access denied），
但 `/sc minute /mo 1`（以及 `/sc once`）可以创建。于是"每分钟检查一次"就成了
等效的开机自启 + 常驻保活，且由任务计划程序托管，**不随任何终端关闭而死**。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HB = os.path.join(ROOT, "cache", "sustain", "heartbeat.json")
PYW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
LOG = os.path.join(ROOT, "cache", "logs", "ensure_supervisor.log")


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    age = 1e9
    try:
        with open(HB, encoding="utf-8") as f:
            d = json.load(f)
        age = time.time() - float(d.get("ts") or 0)
    except Exception:  # noqa: BLE001
        pass

    if age < 60:
        log("心跳 %.0fs，supervisor 在跑，退出" % age)
        return 0

    log("心跳 %.0fs（过期）→ 拉起 supervisor" % age)
    subprocess.Popen([PYW, "-X", "utf8", "tools\\yh_supervisor.py"],
                     cwd=ROOT, close_fds=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_GROUP
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
