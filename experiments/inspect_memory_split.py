# -*- coding: utf-8 -*-
"""看记忆现状：本体库 vs 群库，各自有多少、最近有没有写。"""
from __future__ import annotations

import glob
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def info(db: str) -> str:
    if not os.path.exists(db):
        return "（不存在）"
    age = (time.time() - os.path.getmtime(db)) / 60
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        counts = []
        for t in tabs:
            try:
                n = c.execute("SELECT COUNT(*) FROM \"%s\"" % t).fetchone()[0]
                if n:
                    counts.append("%s=%d" % (t, n))
            except Exception:  # noqa: BLE001
                pass
        c.close()
        return "%.0f 分钟前写入｜%s" % (age, "，".join(counts) or "空")
    except Exception as ex:  # noqa: BLE001
        return "读取失败 %s" % ex


print("=== 群聊记忆库 cache/qq_groups/*.db ===")
for p in sorted(glob.glob(os.path.join(YH, "cache", "qq_groups", "*.db"))):
    print("  %-42s %s" % (os.path.basename(p), info(p)))

print("\n=== 本体记忆库（可能的路径）===")
cands = glob.glob(os.path.join(YH, "cache", "memstore", "*.db")) + \
        glob.glob(os.path.join(YH, "cache", "*.db"))
for p in sorted(cands):
    n = os.path.basename(p)
    if n.startswith(("embvec", "entity_graph", "review_jobs")):
        continue
    print("  %-42s %s" % (n, info(p)))

print("\n=== 会话文件（她与谁聊过）===")
for p in sorted(glob.glob(os.path.join(YH, "cache", "sessions", "qq_*.json")),
                key=lambda x: -os.path.getmtime(x))[:6]:
    print("  %-42s %.0f 分钟前" % (os.path.basename(p), (time.time() - os.path.getmtime(p)) / 60))
