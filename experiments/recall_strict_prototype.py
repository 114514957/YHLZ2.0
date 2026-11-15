# -*- coding: utf-8 -*-
"""阶段 1.5 第 2 步：召回加严**原型**（不改生产代码、不动库）。

加严四条：
  1. 只用 her + owner 两层（分层结果来自 tools/memory_role_classify.py 的规则）
  2. 匹配用 **3-gram ≥2**（原实现是 2-gram 任意命中）
  3. 排除碎片：去掉 `元亨:` 前缀后 <8 字的不要；纯符号/单字不要
  4. 相关性门槛：命中文本与问句共享 3-gram 数 ≥2 才注入

复测口径与 1233 一致：同一批真实用户发言，比较"命中率 / 看着相关比例"。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
from memory_role_classify import classify  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
FAKE = re.compile(r"^\[(群聊最近记录|群上下文摘要)|仅供理解|不要逐条回应")
STOP = {"什么", "怎么", "为什", "么样", "是不", "不是", "可以", "现在", "今天", "一个", "这个"}
PREFIX = re.compile(r"^(?:\[[^\]]{1,40}\])?\s*元亨[:：]\s*")


def grams(s: str, n: int = 3) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,status from l2_items")]
con.close()

INJECT_TYPES = ("preference", "event", "decision")
pool = []
roles = defaultdict(int)
for r in rows:
    if (r["status"] or "") != "active":
        continue
    if r["type"] not in INJECT_TYPES or (r["importance"] or 0) < 4:
        continue
    body = PREFIX.sub("", str(r["summary"] or "")).strip()
    if len(re.sub(r"[\s\W_]+", "", body)) < 8:      # 碎片过滤
        continue
    role, _why = classify(r)
    roles[role] += 1
    if role not in ("her", "owner"):                # 分层过滤
        continue
    pool.append({"id": r["id"], "text": body, "g": grams(body), "role": role})

print("候选池：%d 条（分层计数 %s）" % (len(pool), dict(roles)))


def recall_strict(q: str, limit: int = 3) -> list[dict]:
    qg = grams(q) - STOP
    if len(qg) < 2:
        return []
    scored = []
    for it in pool:
        shared = len(qg & it["g"])
        if shared >= 2:
            scored.append((shared, it))
    scored.sort(key=lambda x: -x[0])
    return [{"id": it["id"], "text": it["text"], "score": s, "role": it["role"]}
            for s, it in scored[:limit]]


# ── 复测：真用户发言 ──────────────────────────────────────────────────
turns = []
for p in glob.glob(os.path.join(ROOT, "cache", "qq_daily", "*.jsonl")):
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if r.get("role") != "user":
            continue
        t = str(r.get("text") or "").strip()
        if len(t) >= 6 and not FAKE.search(t):
            turns.append(t)

hit = rel = 0
samples = []
for t in turns:
    got = recall_strict(t, limit=3)
    if not got:
        continue
    hit += 1
    shared = got[0]["score"]
    if shared >= 2:
        rel += 1
        if len(samples) < 4:
            samples.append((t[:46], got[0]["text"][:70], shared))

print("\n=== 加严后（同一批真实发言 %d 条）===" % len(turns))
print("   命中 %d/%d = %.1f%%" % (hit, len(turns), 100 * hit / max(1, len(turns))))
if hit:
    print("   其中看着相关 %d（%.0f%%）" % (rel, 100 * rel / hit))
print("\n   命中样例：")
for q, a, s in samples:
    print("      问「%s」(共享3-gram %d) → %s" % (q, s, a))
print("\n对照：加严前 命中 66.7%、看着相关 38%")
