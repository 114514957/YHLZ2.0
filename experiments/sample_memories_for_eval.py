# -*- coding: utf-8 -*-
"""抽样：给"召回评测集"出题用（只读）。

按分层选样本：owner/her 里挑「她能答得出、且值得记住」的条目，打印 id + 全文。
"""
from __future__ import annotations

import io
import json
import os
import random
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
from memory_role_classify import classify  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,status from l2_items where status='active'")]
con.close()

by_role = {"her": [], "owner": []}
for r in rows:
    role, _ = classify(r)
    if role in by_role:
        by_role[role].append(r)

random.seed(20261115)
for role in ("owner", "her"):
    items = by_role[role]
    print("=" * 76)
    print("### %s（%d 条 active）" % (role, len(items)))
    for r in random.sample(items, min(22, len(items))):
        t = str(r["summary"]).replace("\n", " ")
        print("\n[%s] %s｜%s｜imp=%s" % (r["id"], r["type"], str(r["source"])[:14], r["importance"]))
        print("   %s" % t[:220])
