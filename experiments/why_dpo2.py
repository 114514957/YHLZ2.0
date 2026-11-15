# -*- coding: utf-8 -*-
"""看 dpo2 的失败项与闸门。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\runs"
p = sorted(glob.glob(os.path.join(RUNS, "*v9t10-dpo2.json")))[-1]
d = json.load(io.open(p, encoding="utf-8"))
for r in d["repeats"][0]["results"]:
    print("%s: %s/%s｜闸门 %s %s" % (r["suite"], r["ok"], r["total"],
                                    r["gate_ok"], r.get("gate_fail")))
    print("   失败：%s" % ",".join(r["failed_ids"]))
print("\n对照 v9t10：56 题 48/56（挂 p06,p10,r02,r03,t13,st02,st03,st05）｜群聊 25/28（挂 g11,g13,g14）")
