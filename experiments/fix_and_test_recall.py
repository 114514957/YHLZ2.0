# -*- coding: utf-8 -*-
"""把已写入的 QQ 记忆 importance 提到 5，并用够长的查询验证能回忆。"""
from __future__ import annotations

import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

DB = ROOT + r"\cache\memstore\memstore.db"
c = sqlite3.connect(DB)
n = c.execute("UPDATE l2_items SET importance=5 WHERE id LIKE 'qqm_%' AND importance<5").rowcount
c.commit()
c.close()
print("提权 %d 条\n" % n)

from backend.target_memory import TargetMemoryService  # noqa: E402

svc = TargetMemoryService()
# 查询必须 >=6 字，且与原文共享 >=2 个二字组
for q in ("你设了我设什么啊", "这个蒸馏的坑第二个是啥", "公皮和私皮都是什么", "为什么把记录通读了一遍"):
    t0 = time.time()
    hits = svc.contextual_recall(q, limit=3)
    print("查「%s」→ %d 条（%.0f ms）" % (q, len(hits), (time.time() - t0) * 1000))
    for h in hits:
        src = str(h.get("source") or "")
        print("   %s %s" % ("★" if src.startswith("qq_") else " ", str(h.get("summary", ""))[:100].replace("\n", " ")))
    print()
