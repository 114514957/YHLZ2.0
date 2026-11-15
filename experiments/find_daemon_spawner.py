# -*- coding: utf-8 -*-
"""找出：谁把 venv daemon 变成"再起一个系统 Python 的 daemon"。

做法：不猜代码，直接问系统——查 19788 的父 7588（venv daemon）启动时的
命令行与它加载过的可疑模块；再全仓搜索"硬编码系统 Python"的字符串。
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psutil  # noqa: E402

ROOT = Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

print("=== 当前 daemon 树 ===")
try:
    for p in psutil.process_iter(["pid", "ppid", "cmdline"]):
        cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
        if "target_daemon" in cl:
            print("  %-6d ← 父 %-6d  %s" % (p.info["pid"], p.info["ppid"], cl[:150]))
except Exception as ex:  # noqa: BLE001
    print("  读不到：%s" % ex)

print("\n=== 全仓搜索：硬编码 'Programs\\\\Python' 或 system 解释器 ===")
needles = ("Programs\\\\Python", "Programs/Python", "Python312", "Python311",
           "SYS_PY", "SYSTEM_PY", "SYSTEM_PYTHON")
hits = 0
for base in ("backend", "tools"):
    for p in (ROOT / base).rglob("*.py"):
        try:
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for n in needles:
            if n in t:
                ln = t[:t.find(n)].count("\n") + 1
                print("  %s:%d  %s" % (p.relative_to(ROOT), ln, n))
                hits += 1
if not hits:
    print("  没找到硬编码系统解释器的字面量")

print("\n=== 搜索：谁在 import/调用 yhlz_launcher 的 _spawn_daemon ===")
for base in ("backend", "tools"):
    for p in (ROOT / base).rglob("*.py"):
        try:
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        if "_spawn_daemon" in t or "_spawn_allowed" in t:
            print("  %s" % p.relative_to(ROOT))
