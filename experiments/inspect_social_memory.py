# -*- coding: utf-8 -*-
"""本体库里 qq_social_* 到底存了什么、能不能当"记忆"用。"""
from __future__ import annotations

import json
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\memstore.db"

c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
c.row_factory = sqlite3.Row

for t in ("qq_social_events", "qq_social_people", "qq_social_edges"):
    print("=== %s ===" % t)
    rows = c.execute("SELECT * FROM %s ORDER BY rowid DESC LIMIT 3" % t).fetchall()
    for r in rows:
        d = dict(r)
        print("   %s" % json.dumps(d, ensure_ascii=False)[:260])
    print()

print("=== 最近 5 条 L2 记忆（本体）===")
for r in c.execute("SELECT * FROM l2_items ORDER BY rowid DESC LIMIT 5"):
    d = dict(r)
    s = str(d.get("summary") or "")[:100]
    print("   [%s] %s｜%s" % (d.get("kind"), s, str(d.get("source"))[:40]))

print("\n=== L2 里有多少条与 QQ 群相关 ===")
for kw in ("群", "qq_g", "QQ"):
    n = c.execute("SELECT COUNT(*) FROM l2_items WHERE summary LIKE ? OR source LIKE ?",
                  ("%%%s%%" % kw, "%%%s%%" % kw)).fetchone()[0]
    print("   包含「%s」：%d 条" % (kw, n))
c.close()
