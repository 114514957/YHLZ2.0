# -*- coding: utf-8 -*-
"""看一眼 QQ 群库的结构和规模，决定怎么捞。"""
from __future__ import annotations

import glob
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\qq_groups"

for p in sorted(glob.glob(os.path.join(D, "*.db"))):
    if ".kw." in p or ".l1." in p:
        continue
    size = os.path.getsize(p) / 1048576
    try:
        con = sqlite3.connect("file:%s?mode=ro" % p.replace("\\", "/"), uri=True)
        tabs = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'").fetchall()]
        print("== %-22s %6.1f MB  表: %s" % (os.path.basename(p), size, tabs))
        for t in tabs:
            try:
                n = con.execute("select count(*) from %s" % t).fetchone()[0]
                cols = [c[1] for c in con.execute("pragma table_info(%s)" % t).fetchall()]
                print("   %-14s %7d 行  列: %s" % (t, n, ",".join(cols[:14])))
            except Exception as ex:  # noqa: BLE001
                print("   %-14s 读不了: %s" % (t, ex))
        con.close()
    except Exception as ex:  # noqa: BLE001
        print("== %s 打不开: %s" % (os.path.basename(p), ex))
