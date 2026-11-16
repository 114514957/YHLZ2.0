# -*- coding: utf-8 -*-
"""用 @/回复关系重算"她被点名"的比例（比"后面有人说话"严格）。"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
HER = {"3655185302"}

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
edges = [dict(r) for r in con.execute(
    "select group_id, sender, target, kind from qq_social_edges")]
con.close()

print("关系 %d 条｜kind：%s" % (len(edges), dict(Counter(e["kind"] for e in edges))))
as_target = [e for e in edges if str(e["target"]) in HER]
as_sender = [e for e in edges if str(e["sender"]) in HER]
print("她被 @/回复：%d 次｜她主动 @/回复别人：%d 次" % (len(as_target), len(as_sender)))
print("按群：")
for g, v in Counter(e["group_id"] for e in as_target).most_common():
    print("   群 %-12s 被点名 %d 次" % (g, v))

# 她的群消息数（用于算比例）
p = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
c2 = sqlite3.connect(p)
c2.row_factory = sqlite3.Row
rows = [dict(r) for r in c2.execute(
    "select group_id, sender_id, length(text) n from group_messages")]
c2.close()
mine = [r for r in rows if str(r["sender_id"]) in HER]
print("\n她发言 %d 条｜被点名 %d 次 → **被点名率 %.1f%%**"
      % (len(mine), len(as_target), 100.0 * len(as_target) / max(1, len(mine))))
for g in sorted({str(r["group_id"]) for r in mine}):
    m = sum(1 for r in mine if str(r["group_id"]) == g)
    t = sum(1 for e in as_target if str(e["group_id"]) == g)
    print("   群 %-12s 发言 %4d｜被点名 %3d（%.1f%%）"
          % (g, m, t, 100.0 * t / max(1, m)))
