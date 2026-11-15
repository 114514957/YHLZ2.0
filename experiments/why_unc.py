# -*- coding: utf-8 -*-
"""看破限基座那轮：闸门挂在哪、失败题是哪些。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"
p = sorted(glob.glob(os.path.join(RUNS, "*unc-dry.json")))[-1]
d = json.load(io.open(p, encoding="utf-8"))
for r in d["repeats"][0]["results"]:
    print("%s: %s/%s｜闸门 %s %s" % (r["suite"], r["ok"], r["total"],
                                    r["gate_ok"], r.get("gate_fail")))
    print("  失败：%s" % ",".join(r["failed_ids"]))
    print()
print("分类得分：")
for r in d["repeats"][0]["results"]:
    if r.get("by_cat"):
        print("  %s %s" % (r["suite"], r["by_cat"]))
