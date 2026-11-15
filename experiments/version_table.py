# -*- coding: utf-8 -*-
"""版本迭代表：把所有存过的 56 题记录用**当前判据**重判，得到可比的分。

为什么要重判：判据从 v1 改到 v6，早期分数记的是旧标准，直接比会得出错误结论
（台账 1079 实测：v8 在 v1 记 43，v3 重判只有 37；v9t6 在 v1 记 42，v2 重判 46）。
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")
sys.path.insert(0, os.path.join(YH, "tools"))
import persona_bank as PB  # noqa: E402

rows = []
for p in sorted(glob.glob(os.path.join(RUNS, "*persona56*.json"))):
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    res = d.get("results") or []
    if not res:
        continue
    ok = 0
    cat = Counter()
    tot = Counter()
    gate = []
    fails = []
    for r in res:
        e = PB.by_id(r["id"])
        if not e:
            continue
        good, _why = PB.verify(e, r.get("answer") or "", tuple(r.get("called") or []))
        c = e.get("cat") or "?"
        tot[c] += 1
        if good:
            ok += 1
            cat[c] += 1
        else:
            fails.append(r["id"])
            if PB.is_gate(e):
                gate.append(r["id"])
    rows.append({
        "tag": d.get("tag") or os.path.basename(p),
        "file": os.path.basename(p),
        "ok": ok, "total": len(res),
        "by_cat": {c: "%d/%d" % (cat[c], tot[c]) for c in tot},
        "gate": gate, "fails": fails,
        "old_score": sum(1 for r in res if r.get("ok")),
    })

print("判据 v%s｜%d 份 56 题记录\n" % (PB.JUDGE_VERSION, len(rows)))
print("%-22s %-8s %-8s %-30s %s" % ("tag", "当时记", "重判", "分类", "闸门"))
for r in sorted(rows, key=lambda x: -x["ok"]):
    print("%-22s %-8s %-8s %-30s %s"
          % (r["tag"][:22], "%d/%d" % (r["old_score"], r["total"]),
             "%d/%d" % (r["ok"], r["total"]),
             " ".join("%s%s" % (c, v) for c, v in r["by_cat"].items()),
             ("✗ " + ",".join(r["gate"])) if r["gate"] else "过"))

out = os.path.join(YH, "docs", "研究", "版本迭代表_20261107.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump({"judge_version": PB.JUDGE_VERSION, "rows": rows}, f,
              ensure_ascii=False, indent=1)
print("\n写出 %s" % out)
