# -*- coding: utf-8 -*-
"""验证 scrub 本身有效吗：把最近带破折号的句子过一遍 scrub，看还剩几成。"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.text_scrub import scrub  # noqa: E402

DB = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
HER = {"3655185302"}
DASH = re.compile(r"[—–―－]")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select group_id, seq, sender_id, text from group_messages order by group_id, seq")]
con.close()

by_g = defaultdict(list)
for r in rows:
    by_g[str(r["group_id"])].append(r)
recent = []
for g, lst in by_g.items():
    recent += [r for r in lst if str(r["sender_id"]) in HER
               and str(r["text"] or "").strip()][-80:]

flagged = [r for r in recent if DASH.search(str(r["text"]))]
print("最近 %d 句｜带破折号 %d 句" % (len(recent), len(flagged)))
still = 0
for r in flagged:
    t = str(r["text"])
    s = scrub(t)
    if DASH.search(s):
        still += 1
        print("  ⚠ scrub 后仍有破折号：%s" % s.replace("\n", " ")[:70])
print("scrub 后仍含破折号：%d / %d" % (still, len(flagged)))
print("→ 若为 0：说明 **scrub 有效**，那 27.5% 是清洗之前的历史/绕过了出口的输出；")
print("→ 若 >0：说明 scrub 有漏（某些破折号变体没覆盖）。")
