# -*- coding: utf-8 -*-
"""起采集器 + 记忆桥（带 -u），并验证它们真的在跑、日志真的有内容。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
LOGS = os.path.join(ROOT, "cache", "logs")
os.makedirs(LOGS, exist_ok=True)

SPAWNS = [
    ("qq_daily_log.py", ["-u", "-B", os.path.join(ROOT, "tools", "qq_daily_log.py"),
                         "--loop", "600", "--review-at", "23:50"],
     os.path.join(LOGS, "qq_daily_log.log")),
    ("qq_memory_bridge.py", ["-u", "-B", os.path.join(ROOT, "tools", "qq_memory_bridge.py"),
                             "--loop", "300"],
     os.path.join(LOGS, "qq_memory_bridge.log")),
]

flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
for name, args, log in SPAWNS:
    f = open(log, "a", encoding="utf-8", errors="replace")
    p = subprocess.Popen([PY] + args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                         creationflags=flags, close_fds=True)
    print("起 %-22s PID %s" % (name, p.pid))

time.sleep(10)

print("\n--- 进程 ---")
try:
    import psutil
    for pr in psutil.process_iter(["pid", "cmdline"]):
        cl = " ".join(str(x) for x in (pr.info.get("cmdline") or []))
        if "qq_daily_log" in cl or "qq_memory_bridge" in cl:
            print("   PID %-6s %s" % (pr.info["pid"],
                                      cl.split("\\tools\\")[-1][:80]))
except Exception as ex:  # noqa: BLE001
    print("   psutil 失败 %s" % ex)

print("\n--- 日志（带 -u 之后应有内容）---")
for name, _a, log in SPAWNS:
    sz = os.path.getsize(log) if os.path.exists(log) else 0
    print("   %-24s %d 字节" % (name, sz))
    if sz:
        with open(log, encoding="utf-8", errors="replace") as f:
            tail = [ln.rstrip() for ln in f.readlines()[-4:]]
        for ln in tail:
            print("        " + ln[:120])
