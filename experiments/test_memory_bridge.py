# -*- coding: utf-8 -*-
"""实测 QQ 记忆桥：造 1 轮测试数据 → dry → 真写 → 查库 → 清理（不留痕）。"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
DAILY = os.path.join(ROOT, "cache", "qq_daily")
TEST_JSONL = os.path.join(DAILY, "29999999.jsonl")
CURSOR = os.path.join(DAILY, "_mem_cursor.json")
MEMDB = os.path.join(ROOT, "cache", "memstore", "memstore.db")

t0 = time.time()
recs = [
    {"ts": t0 - 30, "day": "29999999", "channel": "qq_g999888777", "idx": 0,
     "role": "user", "text": "你昨天说的那个蒸馏的坑，第二个是啥来着", "backfill": False},
    {"ts": t0 - 29, "day": "29999999", "channel": "qq_g999888777", "idx": 1,
     "role": "assistant", "text": "按答错代价加权。政策条款才占七个点，错一条赔得最狠，这种就得单拎出来多喂。",
     "backfill": False},
]
with io.open(TEST_JSONL, "w", encoding="utf-8") as f:
    for r in recs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("[1] 试运行")
r = subprocess.run([PY, os.path.join(ROOT, "tools", "qq_memory_bridge.py"), "--dry"],
                   cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("   " + (r.stdout or r.stderr).strip().replace("\n", "\n   "))

print("\n[2] 真写")
r = subprocess.run([PY, os.path.join(ROOT, "tools", "qq_memory_bridge.py")],
                   cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("   " + (r.stdout or r.stderr).strip().replace("\n", "\n   "))

print("\n[3] 查库")
c = sqlite3.connect(MEMDB)
c.row_factory = sqlite3.Row
rows = c.execute("SELECT id,importance,source,kind,summary,created_at "
                 "FROM l2_items WHERE id LIKE 'qqm_%' ORDER BY rowid DESC LIMIT 3").fetchall()
if not rows:
    print("   ❌ 没写进去")
for x in rows:
    print("   %s｜imp=%s｜src=%s｜%s" % (x["id"], x["importance"], x["source"],
                                        str(x["summary"])[:100]))

print("\n[4] 清理（删测试行 + 测试文件 + 回退游标）")
if rows:
    ids = [x["id"] for x in rows]
    for i in ids:
        c.execute("DELETE FROM l2_items WHERE id=?", (i,))
    c.commit()
    print("   删除 L2 测试行 %d 条" % len(ids))
c.close()
os.remove(TEST_JSONL)
try:
    cur = json.load(io.open(CURSOR, encoding="utf-8"))
    cur.pop("qq_g999888777", None)
    io.open(CURSOR, "w", encoding="utf-8").write(json.dumps(cur, ensure_ascii=False))
except Exception:  # noqa: BLE001
    pass
print("   已删测试文件与游标项")

c = sqlite3.connect(MEMDB)
left = c.execute("SELECT COUNT(*) FROM l2_items WHERE id LIKE 'qqm_%'").fetchone()[0]
tot = c.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0]
c.close()
print("\n   残留 qqm_ 行：%d（应为 0）｜本体 L2 总数：%d" % (left, tot))
