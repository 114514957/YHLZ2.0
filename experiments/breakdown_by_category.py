# -*- coding: utf-8 -*-
"""按类别拆 v13 vs 基线：到底是"全崩"还是"局部塌陷"。"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

NEW = json.load(open(os.path.join(ROOT, "cache", "eval_v13.json"), encoding="utf-8"))
BASE = json.load(open(os.path.join(ROOT, "cache", "eval_基线b_带工具.json"), encoding="utf-8"))


def by_cat(d: dict) -> dict:
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "fail": []})
    for r in d["detail"]["persona"]:
        cat = r.get("cat") or ("工具遵循" if str(r["id"]).startswith("t")
                               else ("关系" if str(r["id"]).startswith("r")
                                     else ("风格" if str(r["id"]).startswith("st") else "人格")))
        agg[cat]["n"] += 1
        if r["ok"]:
            agg[cat]["ok"] += 1
        else:
            agg[cat]["fail"].append(r["id"])
    return agg


b, v = by_cat(BASE), by_cat(NEW)
print("类别        基线       v13        变化")
print("-" * 56)
order = sorted({*b, *v}, key=lambda c: -(b.get(c, {}).get("n", 0)))
for cat in order:
    bb, vv = b.get(cat, {"ok": 0, "n": 0}), v.get(cat, {"ok": 0, "n": 0})
    delta = vv["ok"] - bb["ok"]
    print("%-10s %2d/%-2d   %2d/%-2d     %+d    挂：%s"
          % (cat, bb["ok"], bb["n"], vv["ok"], vv["n"], delta,
             ",".join(vv["fail"]) or "无"))
print("-" * 56)
print("合计       %2d/%-2d   %2d/%-2d" % (
    sum(x["ok"] for x in b.values()), sum(x["n"] for x in b.values()),
    sum(x["ok"] for x in v.values()), sum(x["n"] for x in v.values())))

g_new = sum(1 for r in NEW["detail"]["group"] if r["ok"])
g_base = sum(1 for r in BASE["detail"]["group"] if r["ok"])
print("群聊 28    %2d/28    %2d/28" % (g_base, g_new))
