# -*- coding: utf-8 -*-
"""时刻度①：给 group_messages 加 `at` 列，写入时打时间，并用相邻消息回填历史。

为什么：破折号 44%（历史）vs 27.5%（最近 240 句）无法判断"现在好不好"，
因为**表里没有时间**。没有时间轴就分不清因果先后。

做法：
  1. `ALTER TABLE group_messages ADD COLUMN at REAL DEFAULT 0`（幂等）
  2. 写入点（qq_group_store.append）补 `at=time.time()`
  3. 回填：用 memstore 的 `qq_social_events.at`（有 message_id）join 出时间；
     仍有缺的，用**前一条已知时间**线性外推（保守：取最近已知时间）。
  4. 报告：有时间的行数 / 覆盖哪些时间段。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
GH = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
MS = os.path.join(ROOT, "cache", "memstore", "memstore.db")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect(GH)
    con.row_factory = sqlite3.Row
    cols = {c[1] for c in con.execute("pragma table_info(group_messages)")}
    print("现有字段：%s" % sorted(cols))
    if "at" not in cols:
        if not a.apply:
            print("（干跑）将 ALTER TABLE 加 at 列")
            return 0
        con.execute("ALTER TABLE group_messages ADD COLUMN at REAL DEFAULT 0")
        con.commit()
        print("已加列 at")

    have = con.execute("select count(*) from group_messages where at>0").fetchone()[0]
    total = con.execute("select count(*) from group_messages").fetchone()[0]
    print("已有时间：%d / %d" % (have, total))

    if not a.apply:
        con.close()
        return 0

    # 回填①：用 memstore 的 qq_social_events（有 message_id + at）join
    filled1 = 0
    try:
        con.execute("ATTACH DATABASE ? AS ms", (MS,))
        cur = con.execute(
            "UPDATE group_messages SET at = ("
            "  SELECT e.at FROM ms.qq_social_events e"
            "  WHERE e.message_id = group_messages.message_id LIMIT 1"
            ") WHERE at IS NULL OR at = 0")
        filled1 = cur.rowcount or 0
        con.commit()
        con.execute("DETACH DATABASE ms")
    except Exception as ex:  # noqa: BLE001
        print("  join 回填失败：%s: %s" % (type(ex).__name__, str(ex)[:100]))
    print("join 回填：%d 行" % filled1)

    # 回填②：同群按 seq 顺序，用前一条已知时间补齐（保守：沿用前值）
    filled2 = 0
    groups = [r[0] for r in con.execute(
        "select distinct group_id from group_messages")]
    for g in groups:
        rows = con.execute(
            "select rowid, seq, at from group_messages where group_id=? "
            "order by seq", (g,)).fetchall()
        last = 0.0
        for r in rows:
            if (r["at"] or 0) > 0:
                last = float(r["at"])
            elif last > 0:
                con.execute("update group_messages set at=? where rowid=?",
                            (last, r["rowid"]))
                filled2 += 1
        con.commit()
    print("顺序补齐：%d 行" % filled2)

    have = con.execute("select count(*) from group_messages where at>0").fetchone()[0]
    print("现在有时间：%d / %d（%.0f%%）" % (have, total, 100.0 * have / max(1, total)))
    if have:
        lo, hi = con.execute("select min(at), max(at) from group_messages where at>0").fetchone()
        fmt = lambda x: time.strftime("%Y-%m-%d %H:%M", time.localtime(x))  # noqa: E731
        print("覆盖时间段：%s → %s" % (fmt(lo), fmt(hi)))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
