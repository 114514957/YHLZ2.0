# -*- coding: utf-8 -*-
"""查她的原话在哪：会话档案 / 每日日志 / 群历史库。"""
from __future__ import annotations

import glob
import io
import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=== ① cache/sessions ===")
files = sorted(glob.glob(os.path.join(ROOT, "cache", "sessions", "*.json")))
print("  文件 %d 个" % len(files))
for p in files[:6]:
    try:
        d = json.load(io.open(p, encoding="utf-8"))
        hist = d.get("history") or []
        asst = [m for m in hist if m.get("role") == "assistant"]
        print("   %-34s turns=%s 条数=%d assistant=%d"
              % (os.path.basename(p), d.get("turns"), len(hist), len(asst)))
    except Exception as ex:  # noqa: BLE001
        print("   %-34s 读不了 %s" % (os.path.basename(p), type(ex).__name__))

print("\n=== ② qq_daily ===")
qd = sorted(glob.glob(os.path.join(ROOT, "cache", "qq_daily", "*.jsonl")))
print("  文件 %d 个" % len(qd))
for p in qd[-3:]:
    n = 0
    roles = {}
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        n += 1
        roles[r.get("role")] = roles.get(r.get("role"), 0) + 1
    print("   %-24s %d 行｜角色 %s" % (os.path.basename(p), n, roles))

print("\n=== ③ 群历史库（lite）===")
p = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
if os.path.exists(p):
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    tabs = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table'")]
    print("  表:", tabs)
    for t in tabs[:3]:
        cols = [c[1] for c in con.execute("pragma table_info(%s)" % t)]
        n = con.execute("select count(*) from %s" % t).fetchone()[0]
        print("   %-14s %d 行｜%s" % (t, n, cols[:8]))
    con.close()
else:
    print("  不存在")
