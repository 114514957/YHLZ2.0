# -*- coding: utf-8 -*-
"""验流式日志：用 -u 起 cover_produce，看日志文件是否秒级增长（30 秒后杀掉）。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
JOB = os.path.join(ROOT, "cache", "sing", "_stream_test")
os.makedirs(JOB, exist_ok=True)
LOG = os.path.join(JOB, "release.log")
AUDIO = os.path.join(ROOT, "cache", "sing", "uploads", "又三郎.m4a")

env = dict(os.environ)
env["PYTHONUNBUFFERED"] = "1"
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

argv = [PY, "-u", os.path.join(ROOT, "tools", "cover_produce.py"),
        AUDIO, "--voice", "bright", "--presets", "e", "--out-dir", JOB,
        "--dry-run"]
print("起：%s -u cover_produce.py ..." % os.path.basename(PY))
lf = open(LOG, "w", encoding="utf-8", errors="replace")
p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT, env=env,
                     creationflags=0x08000000)

prev = 0
for t in (30, 60, 90, 120, 150):
    time.sleep(t - prev)
    prev = t
    sz = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    print("  %3d 秒后日志 %d 字节" % (t, sz))
    if sz:
        break

p.kill()
try:
    p.wait(timeout=10)
except Exception:  # noqa: BLE001
    pass
lf.close()
print("\n--- 日志前 6 行 ---")
try:
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for i, ln in enumerate(f):
            if i >= 6:
                break
            print("   " + ln.rstrip()[:160])
except Exception as ex:  # noqa: BLE001
    print("   读不了 %s" % ex)

import shutil  # noqa: E402

shutil.rmtree(JOB, ignore_errors=True)
print("\n（测试目录已清理）")
