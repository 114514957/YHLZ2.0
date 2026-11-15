# -*- coding: utf-8 -*-
"""量化"空文本记忆" + 抽取有文本的条目用于出题。"""
from __future__ import annotations

import io
import json
import os
import random
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
from memory_role_classify import classify  # noqa: E402

con = sqlite3.connect(os.path.join(ROOT, "cache", "memstore", "memstore.db"))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,status,keywords,evidence_ref from l2_items")]
con.close()

def blank(r) -> bool:
    return len(str(r["summary"] or "").strip()) == 0

n = len(rows)
nb = sum(1 for r in rows if blank(r))
print("总计 %d 条｜**文本为空 %d 条（%.1f%%）**" % (n, nb, 100 * nb / n))
if nb:
    print("   空文本的 type：%s" % dict(Counter(str(r["type"]) for r in rows if blank(r))))
    print("   空文本的 source：%s" % dict(Counter(str(r["source"])[:18] for r in rows if blank(r)).most_common(5)))
    print("   空文本的 importance：%s" % dict(Counter(str(r["importance"]) for r in rows if blank(r))))
    print("   空文本但 evidence_ref 非空：%d"
          % sum(1 for r in rows if blank(r) and str(r.get("evidence_ref") or "").strip()))
    print("   样例：%s" % [(r["id"][:12], r["type"], r["importance"], repr(str(r["summary"]))[:20])
                          for r in rows if blank(r)][:4])

ok = [r for r in rows if (not blank(r)) and str(r["status"]) == "active"
      and len(str(r["summary"]).strip()) >= 12]
by_role = {"owner": [], "her": []}
for r in ok:
    role, _ = classify(r)
    if role in by_role:
        by_role[role].append(r)
print("\n可用于出题（active + 有文本 ≥12 字）：owner %d｜her %d"
      % (len(by_role["owner"]), len(by_role["her"])))

random.seed(1)
for role in ("owner", "her"):
    print("\n" + "=" * 70)
    print("### %s 候选（前 16 条全文）" % role)
    for r in random.sample(by_role[role], min(16, len(by_role[role]))):
        txt = " ".join(str(r["summary"]).split())
        print("\n[%s] %s" % (r["id"], r["type"]))
        print("   %s" % txt[:200])
