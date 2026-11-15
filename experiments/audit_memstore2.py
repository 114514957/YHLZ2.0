# -*- coding: utf-8 -*-
"""查记忆库的四个疑点：
  ① FTS 只索引 740/1022 —— 差的是哪些？会不会检索不到？
  ② 556 条 source 为空——它们是什么？
  ③ 275 条"前 20 字相同"——真重复还是不同事实？
  ④ importance=5 占 64%——分布是否退化
"""
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

q = lambda s: [dict(r) for r in con.execute(s).fetchall()]

print("=== ① FTS 覆盖 ===")
n_all = q("select count(*) c from l2_items")[0]["c"]
n_fts = q("select count(*) c from l2_fts")[0]["c"]
print("   主表 %d｜FTS %d｜差 %d" % (n_all, n_fts, n_all - n_fts))
print("   status 分布：%s" % dict(Counter(str(r["status"]) for r in q("select status from l2_items"))))
print("   lifecycle 分布：%s"
      % dict(Counter(str(r["lifecycle"]) for r in q("select lifecycle from l2_items"))))
miss = q("""select i.id, i.status, i.lifecycle, i.type, i.importance
            from l2_items i left join l2_fts f on f.sid = i.id
            where f.sid is null""")
print("   不在 FTS 的：%d 条" % len(miss))
if miss:
    print("      其中 status：%s" % dict(Counter(str(r["status"]) for r in miss)))
    print("      其中 lifecycle：%s" % dict(Counter(str(r["lifecycle"]) for r in miss)))
    print("      样例：%s" % [(r["id"][:10], r["type"], r["status"]) for r in miss[:5]])

print("\n=== ② source 为空的 556 条 ===")
empty_src = q("select * from l2_items where source is null or source=''")
print("   %d 条｜type：%s" % (len(empty_src),
                              dict(Counter(str(r["type"]) for r in empty_src))))
def ts(v) -> str:
    try:
        import datetime as dt
        return dt.datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return str(v)[:10]


print("   created_at 最早/最晚：%s / %s"
      % (ts(min((r["created_at"] or 0) for r in empty_src)),
         ts(max((r["created_at"] or 0) for r in empty_src))))
print("   evidence_ref 非空的：%d 条" % sum(1 for r in empty_src if r.get("evidence_ref")))
for r in empty_src[:4]:
    print("      [%s|imp=%s|%s] %s" % (r["type"], r["importance"], ts(r["created_at"]),
                                       str(r["summary"])[:80]))

print("\n=== ③ 近似重复（前 20 字相同）===")
rows = q("select id, summary, type, source from l2_items")
pre = {}
for r in rows:
    k = re.sub(r"\s+", "", str(r["summary"] or ""))[:20]
    if len(k) >= 20:
        pre.setdefault(k, []).append(r)
dups = {k: v for k, v in pre.items() if len(v) > 1}
print("   冲突组 %d 组，涉及 %d 条" % (len(dups), sum(len(v) for v in dups.values())))
for k, v in list(dups.items())[:3]:
    print("   组：%s" % k)
    for r in v[:3]:
        print("      - %s｜%s｜%s" % (r["id"][:10], r["type"], str(r["summary"])[:80]))

print("\n=== ④ importance 退化？ ===")
for r in q("select importance, count(*) c from l2_items group by importance order by c desc"):
    print("   importance=%-3s %4d 条" % (r["importance"], r["c"]))

print("\n=== ⑤ 最近被检索过的（access_count>0）===")
acc = q("select count(*) c from l2_items where access_count>0")[0]["c"]
print("   被检索过：%d 条 / %d（%.1f%%）" % (acc, len(rows), 100 * acc / len(rows)))
top = q("select id,type,access_count,last_accessed,summary from l2_items "
        "where access_count>0 order by access_count desc limit 5")
for r in top:
    print("      %s×%-3s %s" % (r["access_count"], r["type"], str(r["summary"])[:70]))
con.close()
