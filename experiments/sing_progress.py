# -*- coding: utf-8 -*-
"""从作业目录产物判断翻唱链路走到哪一步 + 子进程状态。"""
from __future__ import annotations

import glob
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

jobs = sorted(glob.glob(os.path.join(ROOT, "cache", "sing", "produce_*")),
              key=lambda p: -os.path.getmtime(p))
if not jobs:
    print("没有 produce_* 作业目录")
    sys.exit(0)

job = jobs[0]
age = (time.time() - os.path.getmtime(job)) / 60
print("最新作业：%s（目录 %.1f 分钟前有写入）" % (os.path.basename(job), age))
print("\n里面的文件（按修改时间）：")
files = []
for root, _d, fs in os.walk(job):
    for f in fs:
        p = os.path.join(root, f)
        files.append((os.path.getmtime(p), os.path.relpath(p, job), os.path.getsize(p)))
for mtime, rel, size in sorted(files):
    print("   %5.1f 分钟前｜%9d B｜%s" % ((time.time() - mtime) / 60, size, rel))
if not files:
    print("   （空——还在第一阶段，或卡在启动）")

print("\n=== 分轨服务健康 ===")
import json
import urllib.request
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for port in (8998, 9000, 8099, 9977):
    try:
        with OP.open("http://127.0.0.1:%d/health" % port, timeout=2) as r:
            print("   %d → %s %s" % (port, r.status, r.read()[:60].decode("utf-8", "replace")))
    except Exception:  # noqa: BLE001
        pass
