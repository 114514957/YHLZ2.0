# -*- coding: utf-8 -*-
"""审计记忆库：962 条到底都是什么、能不能被大模型继承。

只读。输出：结构 / 类型 / 来源 / 长度 / 重复 / 垃圾 / 样本。
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== ① 表结构 ===")
tables = [r[0] for r in cur.execute(
    "select name from sqlite_master where type='table'").fetchall()]
print("   表：%s" % tables)
for t in tables:
    cols = [c[1] for c in cur.execute("pragma table_info(%s)" % t).fetchall()]
    n = cur.execute("select count(*) from %s" % t).fetchone()[0]
    print("   %-18s %5d 行｜字段 %s" % (t, n, cols))

# 找主表
main = None
for cand in ("l2_items", "items", "memories", "l2"):
    if cand in tables:
        main = cand
        break
if main is None:
    main = max(tables, key=lambda t: cur.execute("select count(*) from %s" % t).fetchone()[0])
print("\n=== ② 主表 %s ===" % main)
cols = [c[1] for c in cur.execute("pragma table_info(%s)" % main).fetchall()]
rows = [dict(r) for r in cur.execute("select * from %s" % main).fetchall()]
print("   行数 %d" % len(rows))

def col(name: str):
    return [r.get(name) for r in rows]


for f in ("type", "source", "importance"):
    if f in cols:
        c = Counter(str(r.get(f)) for r in rows)
        print("\n   %s 分布（前 10）：" % f)
        for k, v in c.most_common(10):
            print("      %-28s %4d" % (k[:28], v))

# 文本字段
text_field = None
for cand in ("summary", "text", "content", "value", "body"):
    if cand in cols:
        text_field = cand
        break
if text_field:
    texts = [str(r.get(text_field) or "") for r in rows]
    lens = [len(t) for t in texts]
    print("\n=== ③ 文本（字段 %s）===" % text_field)
    print("   总字数 %d｜均长 %.0f｜最短 %d｜最长 %d"
          % (sum(lens), sum(lens) / len(lens), min(lens), max(lens)))
    empty = sum(1 for t in texts if not t.strip())
    tiny = sum(1 for t in texts if 0 < len(t.strip()) <= 4)
    print("   空 %d 条｜≤4 字 %d 条" % (empty, tiny))

    # 重复
    def norm(t: str) -> str:
        return re.sub(r"\s+", "", t)

    hashes = Counter(hashlib.sha1(norm(t).encode()).hexdigest() for t in texts)
    dup = sum(v - 1 for v in hashes.values() if v > 1)
    print("   完全重复（去空白后）：%d 条冗余" % dup)

    # 近似重复（按前 20 字）
    pre = Counter(norm(t)[:20] for t in texts if len(norm(t)) >= 20)
    near = sum(v - 1 for v in pre.values() if v > 1)
    print("   近似重复（前 20 字相同）：%d 条" % near)

    # 垃圾特征
    junk = {
        "含系统提示脚手架": sum(1 for t in texts if "群聊最近记录" in t or "仅供理解" in t),
        "含【】结构标题": sum(1 for t in texts if re.search(r"【[^】]{2,12}】", t)),
        "像问答对": sum(1 for t in texts if re.match(r"^\s*(Q|问)[:：]", t)),
        "含日期时间戳": sum(1 for t in texts if re.search(r"\d{4}-\d{2}-\d{2}", t)),
        "含 user_id": sum(1 for t in texts if "user_id" in t),
    }
    print("\n=== ④ 垃圾特征 ===")
    for k, v in junk.items():
        print("   %-20s %d 条" % (k, v))

    print("\n=== ⑤ 样本（随机 8 条，看质感）===")
    import random
    random.seed(7)
    for r in random.sample(rows, min(8, len(rows))):
        t = str(r.get(text_field) or "").replace("\n", " ")
        print("   [%-8s|%s|imp=%-3s] %s"
              % (str(r.get("type"))[:8], str(r.get("source"))[:14],
                 r.get("importance"), t[:110]))

con.close()
