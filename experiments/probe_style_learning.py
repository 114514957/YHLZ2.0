# -*- coding: utf-8 -*-
"""说话风格学习的可行性探查：她自己的群聊句子 + 是否被回应。

要点：学习目标是**人格与说话风格**，所以要的是"哪句被接、哪句没人理、哪句违规"，
而不是"群里聊了什么"。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select group_id, message_id, sender, summary, at from qq_social_events")]
edges = [dict(r) for r in con.execute(
    "select group_id, sender, target, kind from qq_social_edges")]
con.close()

print("事件 %d 条｜关系 %d 条" % (len(rows), len(edges)))
print("发送者分布（前 6）：")
for k, v in Counter(r["sender"] for r in rows).most_common(6):
    print("   %-12s %d" % (k, v))

# 她的号：3655185302（元亨）；也可能是 2258374446（老爹）
for uin, label in (("3655185302", "元亨"), ("2258374446", "老爹")):
    mine = [r for r in rows if str(r["sender"]) == uin]
    print("\n%s(%s) 发言 %d 条" % (label, uin, len(mine)))
    if not mine:
        continue
    # 被回应：同群 120 秒内 别人的消息
    by_g = defaultdict(list)
    for r in rows:
        by_g[r["group_id"]].append(r)
    for g in by_g:
        by_g[g].sort(key=lambda x: x["at"] or 0)
    got = 0
    for r in mine:
        nxt = [x for x in by_g[r["group_id"]]
               if (x["at"] or 0) > (r["at"] or 0) and (x["at"] or 0) - (r["at"] or 0) <= 120
               and str(x["sender"]) != uin]
        if nxt:
            got += 1
    print("   120 秒内被搭话：%d/%d = %.0f%%" % (got, len(mine), 100.0 * got / len(mine)))
    lens = [len(str(r["summary"] or "")) for r in mine]
    print("   平均长度 %.0f 字｜最长 %d｜最短 %d" % (sum(lens) / len(lens), max(lens), min(lens)))
    # 反问收尾 / 破折号
    q = sum(1 for r in mine if str(r["summary"] or "").rstrip(" 　\"'」』）)")[-1:] in ("？", "?"))
    dash = sum(1 for r in mine if "—" in str(r["summary"] or ""))
    print("   反问收尾 %d（%.0f%%）｜含破折号 %d（%.0f%%）"
          % (q, 100.0 * q / len(mine), dash, 100.0 * dash / len(mine)))
    print("   样例：")
    for r in mine[:4]:
        print("     [%d 字] %s" % (len(str(r["summary"] or "")), str(r["summary"])[:60]))
