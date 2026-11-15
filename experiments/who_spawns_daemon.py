# -*- coding: utf-8 -*-
"""抓"谁在起第二个 daemon"：监视 20 秒，记录每个新 daemon 的**父进程**。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psutil  # noqa: E402


def daemons():
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
        if "target_daemon" in cl and "restart_daemon" not in cl:
            out.append((p.info["pid"], ".venv" in cl))
    return out


print("开始监视 20 秒…")
seen: dict[int, bool] = {}
for i in range(10):
    for pid, is_venv in daemons():
        if pid in seen:
            continue
        seen[pid] = is_venv
        try:
            proc = psutil.Process(pid)
            ppid = proc.ppid()
            try:
                par = psutil.Process(ppid)
                pcl = " ".join(str(x) for x in (par.cmdline() or []))[:110]
                pname = par.name()
            except Exception:  # noqa: BLE001
                pname, pcl = "（已退出）", ""
            print("  daemon %-6d venv=%-5s ← 父 %-6d %s %s"
                  % (pid, is_venv, ppid, pname, pcl))
        except Exception as ex:  # noqa: BLE001
            print("  daemon %-6d venv=%-5s （读不到父进程：%s）"
                  % (pid, is_venv, type(ex).__name__))
    time.sleep(2)

print("\n共见到 %d 个 daemon，当前：%s"
      % (len(seen), daemons() or "无"))
