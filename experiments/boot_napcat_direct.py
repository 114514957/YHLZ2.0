# -*- coding: utf-8 -*-
"""直接注入启动：跳过 launcher-user.bat（它在没有真实控制台时会 pause 退出）。

老爹 2026-11-16：QQ 桥必须**普通权限**（管理员注入不进 QQ）。本进程已是普通权限。
launcher-user.bat 做的事（读注册表找 QQ.exe → 写 loadNapCat.js → 调 NapCatWinBootMain），
这里照抄，但**不经过 bat**，因此不会被末尾的 pause 打断。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SHELL = r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell"
QQ = r"C:\Program Files\Tencent\QQNT\QQ.exe"
UIN = "3655185302"
LOG = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\logs\napcat_boot.log"

for f in ("NapCatWinBootMain.exe", "NapCatWinBootHook.dll", "napcat.mjs"):
    p = os.path.join(SHELL, f)
    print("%s %s" % ("✅" if os.path.exists(p) else "❌", f))
if not os.path.exists(QQ):
    sys.exit("找不到 QQ.exe")

# ① loadNapCat.js（bat 里也是这么写的）。shell 目录可能不可写 → 退到 cache。
main_js = os.path.join(SHELL, "napcat.mjs").replace("\\", "/")
CACHE = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\tmp"
os.makedirs(CACHE, exist_ok=True)
load_js = None
for cand in (os.path.join(SHELL, "loadNapCat.js"), os.path.join(CACHE, "loadNapCat.js")):
    try:
        io.open(cand, "w", encoding="utf-8").write(
            '(async () => {await import("file:///%s")})()\n' % main_js)
        load_js = cand
        break
    except Exception:  # noqa: BLE001
        continue
if not load_js:
    sys.exit("loadNapCat.js 写不进去（shell 与 cache 都被拒）")
print("loadNapCat.js → %s" % load_js)

env = dict(os.environ)
env["NAPCAT_PATCH_PACKAGE"] = os.path.join(SHELL, "qqnt.json")
env["NAPCAT_LOAD_PATH"] = load_js
env["NAPCAT_INJECT_PATH"] = os.path.join(SHELL, "NapCatWinBootHook.dll")
env["NAPCAT_LAUNCHER_PATH"] = os.path.join(SHELL, "NapCatWinBootMain.exe")
env["NAPCAT_MAIN_PATH"] = main_js

# ② 清掉可能的残留
for name in ("QQ.exe", "NapCatWinBootMain.exe"):
    subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
time.sleep(2)

# ③ 直接调注入器（普通权限 + 新控制台；不重定向 stdin，避免 pause 类问题）
log = io.open(LOG, "w", encoding="utf-8", errors="replace")
proc = subprocess.Popen(
    [os.path.join(SHELL, "NapCatWinBootMain.exe"), QQ,
     os.path.join(SHELL, "NapCatWinBootHook.dll"), UIN],
    cwd=SHELL, env=env, stdout=log, stderr=subprocess.STDOUT,
    close_fds=True, creationflags=0x00000010)   # CREATE_NEW_CONSOLE
print("注入器 pid=%s，日志 %s" % (proc.pid, LOG))

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(20):
    time.sleep(5)
    try:
        with op.open("http://127.0.0.1:8321/state", timeout=8) as f:
            q = (json.loads(f.read().decode()) or {}).get("qq") or {}
        print("  [%2ds] online=%s ws=%s" % ((i + 1) * 5, q.get("online"), q.get("ws")))
        if q.get("online") and q.get("ws"):
            print("✅ 已登录")
            sys.exit(0)
    except Exception as ex:  # noqa: BLE001
        print("  [%2ds] /state 取不到 %s" % ((i + 1) * 5, type(ex).__name__))

print("⚠ 100 秒未登录；看 %s" % LOG)
try:
    tail = io.open(LOG, encoding="utf-8", errors="replace").read()[-600:]
    print("日志尾部：\n%s" % tail)
except Exception:  # noqa: BLE001
    pass
