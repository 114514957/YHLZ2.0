# -*- coding: utf-8 -*-
"""① 清掉刚写进本体记忆的脚手架垃圾 ② 看群会话文件真实结构。"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MEMDB = os.path.join(ROOT, "cache", "memstore", "memstore.db")

print("① 清理 qqm_ 测试/脚手架行")
c = sqlite3.connect(MEMDB)
ids = [r[0] for r in c.execute("SELECT id FROM l2_items WHERE id LIKE 'qqm_%'")]
for i in ids:
    c.execute("DELETE FROM l2_items WHERE id=?", (i,))
c.commit()
left = c.execute("SELECT COUNT(*) FROM l2_items WHERE id LIKE 'qqm_%'").fetchone()[0]
tot = c.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0]
print("   删了 %d 条｜残留 %d｜本体 L2 总数 %d" % (len(ids), left, tot))
c.close()

print("\n② 群会话文件结构（看 user 里到底存了什么）")
for name in ("qq_qq_g1094579571.json", "qq_qq_g1121723665.json"):
    p = os.path.join(ROOT, "cache", "sessions", name)
    if not os.path.exists(p):
        continue
    d = json.load(io.open(p, encoding="utf-8"))
    h = d.get("history") or []
    print("\n--- %s｜%d 条｜title=%s" % (name, len(h), d.get("title")))
    for m in h[-4:]:
        role = m.get("role")
        txt = (m.get("content") or "").replace("\n", " ⏎ ")
        print("   %-9s %s" % (role, txt[:150]))
