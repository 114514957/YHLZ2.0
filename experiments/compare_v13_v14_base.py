# -*- coding: utf-8 -*-
"""v13 / v14 / 基线 三版按类别对拍。"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FILES = [("基线", "eval_基线b_带工具.json"), ("v13", "eval_v13.json"), ("v14", "eval_v14.json")]


def by_cat(path: str) -> dict:
    d = json.load(open(os.path.join(ROOT, "cache", path), encoding="utf-8"))
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "fail": []})
    for r in d["detail"]["persona"]:
        i = str(r["id"])
        cat = r.get("cat") or ("工具遵循" if i.startswith("t") else
                               ("关系" if i.startswith("r") else
                                ("风格" if i.startswith("st") else "人格")))
        agg[cat]["n"] += 1
        if r["ok"]:
            agg[cat]["ok"] += 1
        else:
            agg[cat]["fail"].append(i)
    g = sum(1 for r in d["detail"]["group"] if r["ok"])
    return {"cats": dict(agg), "group": g,
            "total": sum(1 for r in d["detail"]["persona"] if r["ok"])}


data = {name: by_cat(f) for name, f in FILES}
cats = ["人格", "工具遵循", "关系", "风格"]
print("%-10s %8s %8s %8s" % ("类别", "基线", "v13", "v14"))
print("-" * 40)
for c in cats:
    cells = []
    for name, _ in FILES:
        a = data[name]["cats"].get(c, {"ok": 0, "n": 0})
        cells.append("%d/%d" % (a["ok"], a["n"]))
    print("%-10s %8s %8s %8s" % (c, *cells))
print("-" * 40)
print("%-10s %8s %8s %8s" % ("合计", *["%d/56" % data[n]["total"] for n, _ in FILES]))
print("%-10s %8s %8s %8s" % ("群聊", *["%d/28" % data[n]["group"] for n, _ in FILES]))
print()
for name, _ in FILES[1:]:
    print("%s 失败明细：%s" % (name,
          {c: data[name]["cats"].get(c, {}).get("fail", []) for c in cats}))
