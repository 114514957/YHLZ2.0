# -*- coding: utf-8 -*-
"""验证：破折号 44% 是历史遗留，还是现在仍在发生。

方法：group_messages 没有时间列，但 seq 单调递增 → 用"每群最后 N 条"
近似"最近"，与全量对比。
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
HER = {"3655185302"}
DASH = re.compile(r"[—–―－]")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select group_id, seq, sender_id, text from group_messages "
    "order by group_id, seq")]
con.close()

by_g = defaultdict(list)
for r in rows:
    by_g[str(r["group_id"])].append(r)

mine_all, mine_recent = [], []
for g, lst in by_g.items():
    hers = [r for r in lst if str(r["sender_id"]) in HER and str(r["text"] or "").strip()]
    mine_all += hers
    mine_recent += hers[-80:]          # 每群最近 80 句


def rate(items) -> tuple[int, int, float]:
    n = len(items)
    d = sum(1 for r in items if DASH.search(str(r["text"])))
    return d, n, (100.0 * d / n if n else 0.0)


for label, items in (("全部历史", mine_all), ("最近 80×群", mine_recent)):
    d, n, p = rate(items)
    print("%-10s %4d 句｜带破折号 %3d（%.1f%%）" % (label, n, d, p))

print("\n最近 10 句原文（看现在还有没有）：")
for r in mine_recent[-10:]:
    t = str(r["text"]).replace("\n", " ")
    mark = "⚠" if DASH.search(t) else " "
    print("  %s %s" % (mark, t[:80]))
