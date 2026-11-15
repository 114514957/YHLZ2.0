# -*- coding: utf-8 -*-
"""端到端核对：语义召回 + 追踪落盘（生产入口 `semantic_recall`）。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.memory_recall_semantic import (SemanticIndex, default_paths,
                                            semantic_recall)
from backend.memory_recall_trace import path as trace_path

db, vec = default_paths(ROOT)
idx = SemanticIndex(vec)
print("索引载入：%s（%d 条）" % (idx.load(db), len(idx._ids)))

tests = [
    ("我不吃香菜，记着点", "应命中：老爹不吃香菜"),
    ("莫高窟你最喜欢哪个窟", "应命中：藏经洞"),
    ("今天上班累死了，想躺会儿", "不该命中：闲聊"),
    ("帮我看看这个报错", "不该命中：工程指令"),
    ("在吗", "不该命中：寒暄"),
]
for q, want in tests:
    got = semantic_recall(q, index=idx, db_path=db, limit=2)
    print("\n问：%s（%s）" % (q, want))
    if not got:
        print("   → 不注入")
    for h in got:
        print("   → [%s] %.3f %s" % (h["role"], h["score"], h["summary"][:56]))

p = trace_path()
print("\n追踪文件：%s｜存在 %s" % (p, p.exists()))
if p.exists():
    lines = io.open(p, encoding="utf-8").read().strip().splitlines()
    print("  行数 %d｜最后一行：%s" % (len(lines), lines[-1][:150] if lines else "—"))
