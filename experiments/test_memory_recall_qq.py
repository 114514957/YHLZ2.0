# -*- coding: utf-8 -*-
"""验：QQ 记忆写进本体后，她真能回忆起来。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

from backend.target_memory import TargetMemoryService  # noqa: E402

svc = TargetMemoryService()

for q in ("蒸馏的坑", "你设了我设什么", "公皮 私皮", "派单"):
    t0 = time.time()
    hits = svc.contextual_recall(q, limit=3)
    print("\n查「%s」→ %d 条（%.0f ms）" % (q, len(hits), (time.time() - t0) * 1000))
    for h in hits:
        src = str(h.get("source") or "")
        mark = "★QQ" if src.startswith("qq_") else "  其他"
        print("   %s %s" % (mark, str(h.get("summary", ""))[:90].replace("\n", " ")))

print("\n库内统计：")
import sqlite3
c = sqlite3.connect(r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\memstore\memstore.db")
print("   L2 总数", c.execute("select count(*) from l2_items").fetchone()[0])
print("   QQ 来源", c.execute("select count(*) from l2_items where source like 'qq_%'").fetchone()[0])
for r in c.execute("select source, count(*) from l2_items where source like 'qq_%' group by source"):
    print("   %-28s %d" % (r[0], r[1]))
c.close()
