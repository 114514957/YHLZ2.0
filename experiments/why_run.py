# -*- coding: utf-8 -*-
"""看某次跑挂在哪：按类别列失败项，闸门单独标出，附原始答案。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TAG = sys.argv[1] if len(sys.argv) > 1 else "20261112-2206-v11"
GATES = {"s06", "r07", "r08", "g03", "g04", "g09", "g14"}

d = json.load(io.open(os.path.join(YH, "experiments", "runs", TAG + ".json"), encoding="utf-8"))
print("exp_id=%s｜judge=%s" % (d.get("exp_id"), d.get("judge_version")))

for suite in d["repeats"][0]["results"]:
    sname = suite.get("suite") or suite.get("name") or "?"
    rows = suite.get("results") or []
    fails = [r for r in rows if not r.get("ok")]
    gate_fails = [r for r in fails if str(r.get("id")) in GATES]
    print("\n=== %s === %d/%d｜闸门挂 %d"
          % (sname, len(rows) - len(fails), len(rows), len(gate_fails)))
    print("  失败：%s" % ",".join(str(r.get("id")) for r in fails))
    for r in fails:
        tag = "【闸门】" if str(r.get("id")) in GATES else "   "
        print("\n %s %s" % (tag, r.get("id")))
        print("   问：%s" % str(r.get("q"))[:60])
        print("   答：%s" % str(r.get("answer"))[:200].replace("\n", " "))
        print("   因：%s" % str(r.get("why"))[:110])
