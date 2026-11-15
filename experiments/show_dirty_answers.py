# -*- coding: utf-8 -*-
"""看脏话探针（g27/g28）她到底怎么答的，并给失败清单。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"
WB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"

p = sorted(glob.glob(os.path.join(RUNS, "*v9t10-dirty.json")))[-1]
d = json.load(io.open(p, encoding="utf-8"))
r = d["repeats"][0]["results"][0]
print("群聊 %s/%s｜闸门 %s %s" % (r["ok"], r["total"], r["gate_ok"], r["gate_fail"]))
print("失败题：%s\n" % ",".join(r["failed_ids"]))

# 找带 answers 的记录（evals 直跑会落盘到 workbench runs）
cands = [x for x in glob.glob(os.path.join(WB, "*.json")) if "v9t10-dirty" in x]
print("带答案的记录：%s" % [os.path.basename(x) for x in cands])
for x in sorted(cands)[-1:]:
    dd = json.load(io.open(x, encoding="utf-8"))
    for row in dd.get("results", []):
        if row["id"] in ("g16", "g17", "g27", "g28", "g11", "g14"):
            print("  %-4s ok=%-5s %r" % (row["id"], row.get("ok"),
                                        (row.get("answer") or "")[:90]))
