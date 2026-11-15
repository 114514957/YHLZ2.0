# -*- coding: utf-8 -*-
"""查"看不见的文本"：只有零宽/空白字符的记忆条目有多少。"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
con = sqlite3.connect(os.path.join(ROOT, "cache", "memstore", "memstore.db"))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,status from l2_items")]
con.close()

INVISIBLE = re.compile(r"^[\s\u200b-\u200f\ufeff\u00a0\u3000]+$")

inv = [r for r in rows if INVISIBLE.match(str(r["summary"] or ""))]
print("总计 %d 条｜**只有零宽/空白字符 %d 条（%.1f%%）**" % (len(rows), len(inv), 100 * len(inv) / len(rows)))
if inv:
    print("   type：%s" % dict(Counter(str(r["type"]) for r in inv)))
    print("   source：%s" % dict(Counter(str(r["source"])[:20] for r in inv).most_common(5)))
    print("   importance：%s" % dict(Counter(str(r["importance"]) for r in inv).most_common(5)))
    print("   status：%s" % dict(Counter(str(r["status"]) for r in inv)))
    print("   样例 repr：")
    for r in inv[:5]:
        print("      %s → %r" % (r["id"], str(r["summary"])[:12]))

# 再查"极短但非空"（≤6 字纯符号）
short = [r for r in rows if 0 < len("".join(str(r["summary"] or "").split())) <= 6]
print("\n极短条目（≤6 字，去空白）：%d 条" % len(short))
for r in short[:6]:
    print("   %s [%s] %r" % (r["id"][:14], r["type"], str(r["summary"])[:20]))
