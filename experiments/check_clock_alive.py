# -*- coding: utf-8 -*-
"""看时刻度是不是活的：群消息有没有新记录（group_history 与 memstore 两路都查）。"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
GH = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
MS = os.path.join(ROOT, "cache", "memstore", "memstore.db")
now = time.time()


def fmt(t: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(t)) if t else "—"


print("=== ① group_history（桥的群历史）===")
con = sqlite3.connect(GH)
con.row_factory = sqlite3.Row
mx = con.execute("select max(at) m, count(*) c from group_messages").fetchone()
print("  最新 %s（距今 %.1f 分钟）｜共 %d 条" % (fmt(mx["m"]), (now - (mx["m"] or now)) / 60, mx["c"]))
new = [dict(r) for r in con.execute(
    "select group_id, sender_name, text, at from group_messages "
    "where at > ? order by at desc limit 5", (now - 1800,))]
print("  近 30 分钟新增：%d 条" % len(new))
for r in new:
    print("    %s [%s] %s" % (fmt(r["at"]), r["sender_name"], str(r["text"])[:46]))
con.close()

print("\n=== ② memstore / qq_social_events（社交采集）===")
con = sqlite3.connect(MS)
con.row_factory = sqlite3.Row
try:
    mx = con.execute("select max(at) m, count(*) c from qq_social_events").fetchone()
    print("  最新 %s（距今 %.1f 分钟）｜共 %d 条"
          % (fmt(mx["m"]), (now - (mx["m"] or now)) / 60, mx["c"]))
    n2 = con.execute("select count(*) from qq_social_events where at > ?",
                     (now - 1800,)).fetchone()[0]
    print("  近 30 分钟新增：%d 条" % n2)
    for r in con.execute("select sender, summary, at from qq_social_events "
                         "where at > ? order by at desc limit 3", (now - 1800,)):
        print("    %s [%s] %s" % (fmt(r["at"]), r["sender"], str(r["summary"])[:46]))
except Exception as ex:  # noqa: BLE001
    print("  查询失败：%s" % type(ex).__name__)
con.close()

print("\n=== ③ 桥/登录状态 ===")
import json
import urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with op.open("http://127.0.0.1:8321/state", timeout=15) as f:
        d = json.loads(f.read().decode())
    q = d.get("qq") or {}
    print("  online=%s ws=%s bridge=%s" % (q.get("online"), q.get("ws"), q.get("bridge")))
except Exception as ex:  # noqa: BLE001
    print("  /state 取不到：%s" % type(ex).__name__)

print("\n=== ④ 结论 ===")
if mx and mx["m"] and (now - mx["m"]) < 600:
    print("  时刻度是活的（10 分钟内还有新数据）")
else:
    print("  ⚠ 两路都没有近期新数据 → 要么群里没消息，要么入库路径没跑")
