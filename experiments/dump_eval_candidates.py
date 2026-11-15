# -*- coding: utf-8 -*-
"""导出候选记忆（供人工出题）→ cache/eval_candidates.json"""
from __future__ import annotations

import io
import json
import os
import random
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
from backend.memory_roles import classify  # noqa: E402

con = sqlite3.connect(os.path.join(ROOT, "cache", "memstore", "memstore.db"))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,status from l2_items where status='active'")]
con.close()

pool = {"owner": [], "her": []}
for r in rows:
    role, _ = classify(r)
    if role not in pool:
        continue
    txt = " ".join(str(r["summary"] or "").split())
    if len(txt) < 12:
        continue
    pool[role].append({"id": r["id"], "type": r["type"], "imp": r["importance"], "text": txt})

random.seed(11)
out = {}
for role in ("owner", "her"):
    items = pool[role]
    random.shuffle(items)
    out[role] = items[:24]

path = os.path.join(ROOT, "cache", "eval_candidates.json")
io.open(path, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
print("owner %d 条｜her %d 条 → %s" % (len(out["owner"]), len(out["her"]),
                                      os.path.relpath(path, ROOT)))
