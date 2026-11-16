# -*- coding: utf-8 -*-
"""记忆分层落库：把 classify() 的结果写进 l2_items.role（含备份）。

为什么（2026-11-16）：
  · 现在每轮召回都要**现场跑规则**给 1000+ 条分类，慢且不透明；
  · 老爹要"记忆分层"，分层结果就该是**库里的事实**，不是每次算的临时值；
  · 落库后：召回只查 role IN ('her','owner')，星图直接按 role 上色，人工复核也有依据。

安全：
  1. 先**整库备份**到 cache/memstore/backup/memstore_<时间戳>.db
  2. 只增列 + 回填，**不改任何原有字段**
  3. 支持 --dry（只看分布，不写库）

用法：
    python tools\\memory_role_migrate.py --dry
    python tools\\memory_role_migrate.py --apply
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
BK = os.path.join(ROOT, "cache", "memstore", "backup")


def backup() -> str:
    os.makedirs(BK, exist_ok=True)
    dst = os.path.join(BK, "memstore_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB, dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    from backend.memory_roles import classify, is_injectable

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cols = {c[1] for c in con.execute("pragma table_info(l2_items)")}
    rows = [dict(r) for r in con.execute(
        "select id, type, summary, source, status from l2_items")]
    print("条目 %d｜已有 role 列：%s" % (len(rows), "role" in cols))

    plan = {}
    dist = {}
    injectable = 0
    for r in rows:
        role, why = classify(r)
        plan[r["id"]] = role
        dist[role] = dist.get(role, 0) + 1
        if is_injectable(role):
            injectable += 1

    print("\n计划落库分布：")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print("  %-12s %4d（%.0f%%）" % (k, v, 100.0 * v / max(1, len(rows))))
    print("可注入（her/owner）：%d 条（%.0f%%）" % (
        injectable, 100.0 * injectable / max(1, len(rows))))

    if a.dry or not a.apply:
        print("\n（干跑；加 --apply 才写库）")
        return 0

    dst = backup()
    print("\n已备份：%s（%.1f MB）"
          % (os.path.relpath(dst, ROOT), os.path.getsize(dst) / 1e6))

    if "role" not in cols:
        con.execute("ALTER TABLE l2_items ADD COLUMN role TEXT DEFAULT ''")
        print("已加列 role")
    con.executemany("update l2_items set role=? where id=?",
                    [(role, iid) for iid, role in plan.items()])
    con.commit()

    got = {r[0]: r[1] for r in con.execute(
        "select role, count(*) from l2_items group by role")}
    print("落库结果：", got)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
