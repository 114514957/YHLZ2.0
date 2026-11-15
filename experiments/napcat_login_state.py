# -*- coding: utf-8 -*-
"""找 NapCat 的登录状态：进程、二维码、日志。"""
from __future__ import annotations

import glob
import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("== NapCat 相关进程 ==")
ps = subprocess.run(["tasklist", "/fi", "imagename eq QQ.exe", "/fo", "csv"],
                    capture_output=True, text=True, errors="replace").stdout
print("   QQ.exe: %s" % ("在跑" if "QQ.exe" in ps else "不在"))
ps2 = subprocess.run(["tasklist", "/fo", "csv", "/v"], capture_output=True,
                     text=True, errors="replace").stdout
for line in ps2.splitlines():
    if "napcat" in line.lower() or "node.exe" in line.lower():
        print("   %s" % line[:130])

print("\n== 找二维码（近期 png/jpg）==")
roots = [os.path.join(YH, "cache", "qq_bridge", "lite"),
         os.path.join(YH, "qqwatch"),
         os.path.join(YH, "cache")]
found = []
for r in roots:
    if not os.path.isdir(r):
        continue
    for p in glob.glob(os.path.join(r, "**", "*.png"), recursive=True) + \
             glob.glob(os.path.join(r, "**", "*.jpg"), recursive=True):
        try:
            age = time.time() - os.path.getmtime(p)
        except Exception:  # noqa: BLE001
            continue
        if age < 1800:
            found.append((age, p))
for age, p in sorted(found)[:10]:
    print("   %.0f 分钟前｜%s" % (age / 60, p))

print("\n== NapCat 日志尾部 ==")
logs = []
for r in roots:
    if os.path.isdir(r):
        logs += glob.glob(os.path.join(r, "**", "*.log"), recursive=True)
logs.sort(key=lambda p: -os.path.getmtime(p))
for p in logs[:3]:
    print("\n--- %s（%.0f 分钟前）" % (p, (time.time() - os.path.getmtime(p)) / 60))
    try:
        t = io.open(p, encoding="utf-8", errors="replace").read()
        print("\n".join(t.splitlines()[-12:]))
    except Exception as ex:  # noqa: BLE001
        print("   读不了 %s" % ex)
