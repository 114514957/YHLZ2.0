# -*- coding: utf-8 -*-
"""核对知识库：群学习写入的 22 条是否落库、category 是否正确。"""
from __future__ import annotations

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

import backend.yuanheng_kb as K  # noqa: E402

db = str(K._db())
print("db:", db)
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table'")]
print("表:", tables)
main = "items" if "items" in tables else tables[0]
cols = [c[1] for c in con.execute("pragma table_info(%s)" % main)]
print("字段:", cols)
try:
    for r in con.execute("select category,count(*) n from %s group by category "
                         "order by n desc limit 10" % main):
        print("  %-10s %d" % (r["category"], r["n"]))
except Exception as ex:  # noqa: BLE001
    print("  分组失败:", ex)
try:
    n = con.execute("select count(*) from %s where summary like '[%%'" % main).fetchone()[0]
    print("  以 [ 开头的条目:", n)
    for r in con.execute("select category,summary from %s where summary like '%%群%%' "
                         "order by rowid desc limit 4" % main):
        print("    [%s] %s" % (r["category"], str(r["summary"])[:60]))
except Exception as ex:  # noqa: BLE001
    print("  样例失败:", ex)
con.close()
