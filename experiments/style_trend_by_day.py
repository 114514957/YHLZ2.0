# -*- coding: utf-8 -*-
"""时刻度②：按天看她的说话风格趋势（有 at 列，之前是我漏看了）。

回答"现在好不好、改动有没有用"：破折号清洗是 11-14 上的，
所以看 11-14 前后的破折号率、反问率、@人率、长度，就能分清因果先后。
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
HER = {"3655185302"}
DASH = re.compile(r"[—–―－]")
TAILQ = re.compile(r"[？?]\s*$")
AT = re.compile(r"\[\[at:\s*\d+\]\]")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select group_id, seq, sender_id, text, at, is_bot from group_messages "
    "where at > 0 order by at")]
con.close()

mine = [r for r in rows if str(r["sender_id"]) in HER and str(r["text"] or "").strip()]
print("她有时刻的发言：%d 条" % len(mine))

by_day = defaultdict(lambda: {"n": 0, "dash": 0, "q": 0, "at": 0, "chars": 0})
for r in mine:
    d = time.strftime("%m-%d", time.localtime(float(r["at"])))
    t = str(r["text"])
    s = by_day[d]
    s["n"] += 1
    s["chars"] += len(t)
    s["dash"] += 1 if DASH.search(t) else 0
    s["q"] += 1 if TAILQ.search(t.strip()) else 0
    s["at"] += 1 if AT.search(t) else 0

print("\n日期    句数  均长  破折号      反问      带@")
print("-" * 52)
for d in sorted(by_day)[-14:]:
    s = by_day[d]
    print("%-6s %4d  %4.0f  %3d(%3.0f%%)  %2d(%2.0f%%)  %2d(%2.0f%%)"
          % (d, s["n"], s["chars"] / s["n"],
             s["dash"], 100.0 * s["dash"] / s["n"],
             s["q"], 100.0 * s["q"] / s["n"],
             s["at"], 100.0 * s["at"] / s["n"]))

# 11-14 前后对比（清洗上线日）
CUT = time.mktime(time.strptime("2026-11-14", "%Y-%m-%d"))
for label, sel in (("清洗前(<11-14)", [r for r in mine if float(r["at"]) < CUT]),
                   ("清洗后(≥11-14)", [r for r in mine if float(r["at"]) >= CUT])):
    n = len(sel)
    if not n:
        print("\n%s：无数据" % label)
        continue
    dash = sum(1 for r in sel if DASH.search(str(r["text"])))
    q = sum(1 for r in sel if TAILQ.search(str(r["text"]).strip()))
    at = sum(1 for r in sel if AT.search(str(r["text"])))
    print("\n%s：%d 句｜破折号 %.1f%%｜反问 %.1f%%｜带@ %.1f%%｜均长 %.0f"
          % (label, n, 100.0 * dash / n, 100.0 * q / n, 100.0 * at / n,
             sum(len(str(r["text"])) for r in sel) / n))
