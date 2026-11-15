# -*- coding: utf-8 -*-
"""翻唱卡住排查：子进程 CPU 时间、命令行、唱窗 flag、服务端口。"""
from __future__ import annotations

import glob
import io
import json
import os
import socket
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

try:
    import psutil
except Exception as ex:  # noqa: BLE001
    sys.exit("psutil 不可用：%s" % ex)

print("=== 相关进程（CPU 时间说明它到底在不在干活）===")
for p in psutil.process_iter(["pid", "name", "cmdline", "cpu_times", "create_time",
                              "status"]):
    cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
    low = cl.lower()
    if not any(k in low for k in ("cover_produce", "svc_mdx", "seed", "svc_")):
        continue
    try:
        ct = p.info.get("cpu_times")
        cpu = (ct.user + ct.system) if ct else 0
        age = time.time() - (p.info.get("create_time") or time.time())
        mem = p.memory_info().rss / 1048576
        print("   PID %-6s 状态 %-9s CPU %7.1fs / 存在 %5.1f 分钟｜RSS %6.0f MB"
              % (p.info["pid"], str(p.info.get("status")), cpu, age / 60, mem))
        print("        %s" % cl[:150])
    except Exception:  # noqa: BLE001
        pass

print("\n=== 唱窗 / 调度 flag ===")
for pat in ("cache/tmp/*sing*", "cache/tmp/*window*", "cache/*.flag",
            "cache/tmp/*.flag"):
    for f in sorted(glob.glob(os.path.join(ROOT, pat))):
        age = (time.time() - os.path.getmtime(f)) / 60
        print("   %-46s %.0f 分钟前" % (os.path.relpath(f, ROOT), age))

print("\n=== 端口 ===")
for port in (8099, 8998, 9000, 18000, 50021):
    s = socket.socket()
    s.settimeout(0.6)
    ok = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if ok:
        print("   %d OPEN" % port)

print("\n=== 作业目录里有没有日志/错误 ===")
jobs = sorted(glob.glob(os.path.join(ROOT, "cache", "sing", "produce_*")),
              key=lambda p: -os.path.getmtime(p))
if jobs:
    for f in sorted(os.listdir(jobs[0])):
        p = os.path.join(jobs[0], f)
        if os.path.isfile(p):
            print("   %-28s %d B" % (f, os.path.getsize(p)))
