# -*- coding: utf-8 -*-
"""对比 v9t10 基线 vs 加了语法+logit-bias 的失败项差异。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"
WB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"


def load(p):
    d = json.load(io.open(p, encoding="utf-8"))
    out = {}
    for r in d["repeats"][0]["results"] if "repeats" in d else d["results"]:
        if "suite" in r:
            out[r["suite"]] = r
        else:
            out.setdefault(d.get("suite"), {"results": []})
    return d


ng = json.load(io.open(sorted(glob.glob(os.path.join(RUNS, "*v9t10-ng.json")))[-1], encoding="utf-8"))
base = json.load(io.open(sorted(glob.glob(os.path.join(WB, "*persona56_v9t10_56.json")))[-1], encoding="utf-8"))
baseg = json.load(io.open(sorted(glob.glob(os.path.join(WB, "*group_v9t10_group.json")))[-1], encoding="utf-8"))

n = {x["suite"]: x for x in ng["repeats"][0]["results"]}
print("== 56 题 ==")
b_fail = {r["id"] for r in base["results"] if not r["ok"]}
n_fail = set(n["persona56"]["failed_ids"])
print("  基线 48/56 失败: %s" % ",".join(sorted(b_fail)))
print("  语法版 47/56 失败: %s" % ",".join(sorted(n_fail)))
print("  ✅ 治好了: %s" % ",".join(sorted(b_fail - n_fail)) or "-")
print("  ❌ 新挂的: %s" % (",".join(sorted(n_fail - b_fail)) or "-"))

print("\n== 群聊 ==")
bg_fail = {r["id"] for r in baseg["results"] if not r["ok"]}
ng_fail = set(n["group"]["failed_ids"])
print("  基线 23/26 失败: %s" % ",".join(sorted(bg_fail)))
print("  语法版 24/26 失败: %s" % ",".join(sorted(ng_fail)))
print("  ✅ 治好了: %s" % (",".join(sorted(bg_fail - ng_fail)) or "-"))
print("  ❌ 新挂的: %s" % (",".join(sorted(ng_fail - bg_fail)) or "-"))
