# -*- coding: utf-8 -*-
"""看最新写入的 QQ 记忆，确认私聊也进去了。"""
from __future__ import annotations

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\memstore\memstore.db"

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
print("L2 总数 %d｜QQ 来源 %d"
      % (c.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0],
         c.execute("SELECT COUNT(*) FROM l2_items WHERE source LIKE 'qq_%'").fetchone()[0]))
print("\n最近 6 条 QQ 记忆：")
for r in c.execute("SELECT source, summary FROM l2_items WHERE source LIKE 'qq_%' "
                   "ORDER BY rowid DESC LIMIT 6"):
    print("  [%s] %s" % (r["source"], str(r["summary"])[:100].replace("\n", " ")))

print("\n按来源统计：")
for r in c.execute("SELECT source, COUNT(*) n FROM l2_items WHERE source LIKE 'qq_%' "
                   "GROUP BY source ORDER BY n DESC"):
    print("   %-26s %d" % (r["source"], r["n"]))
c.close()
