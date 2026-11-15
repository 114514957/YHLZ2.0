# -*- coding: utf-8 -*-
"""最小探针：语义嵌入在本机能不能用（决定记忆召回能否上语义检索）。

只做三件事：① 能不能 import/加载模型 ② 嵌入 3 条要多久 ③ 维度多少。
失败就把原因原样打印，不猜。
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

print("=== ① 语义模型闸门 ===")
try:
    from backend.memory_resource_policy import semantic_model_allowed
    print("   semantic_model_allowed() =", semantic_model_allowed())
except Exception as ex:  # noqa: BLE001
    print("   取不到闸门：%s: %s" % (type(ex).__name__, ex))

print("\n=== ② 嵌入模型 ===")
try:
    from backend import vector_memory as VM
    print("   模块字段：%s" % [n for n in dir(VM) if not n.startswith("_")][:12])
    t0 = time.time()
    vecs = VM.embed_cls(["老爹不吃香菜", "记忆可以遗忘但模式永存", "今天天气不错"])
    dt = time.time() - t0
    print("   ✅ 可用｜3 条耗时 %.2f 秒｜维度 %s" % (dt, getattr(vecs, "shape", "?")))
except Exception as ex:  # noqa: BLE001
    print("   ❌ 不可用：%s: %s" % (type(ex).__name__, ex))

print("\n=== ③ 台账向量库现状 ===")
import sqlite3  # noqa: E402
p = os.path.join(ROOT, "cache", "embvec.db")
if os.path.exists(p):
    con = sqlite3.connect(p)
    tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    print("   表：%s" % tabs)
    for t in tabs:
        try:
            n = con.execute("select count(*) from %s" % t).fetchone()[0]
            cols = [c[1] for c in con.execute("pragma table_info(%s)" % t)]
            print("   %-16s %6d 行｜字段 %s" % (t, n, cols[:8]))
        except Exception as ex:  # noqa: BLE001
            print("   %-16s 读不了：%s" % (t, ex))
    con.close()
else:
    print("   没有 embvec.db")
