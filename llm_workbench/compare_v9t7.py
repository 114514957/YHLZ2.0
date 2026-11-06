# -*- coding: utf-8 -*-
"""v9t7 vs v9t6：同判据对比 + 看关键失败题的原始回答。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "tools"))
import persona_bank as PB  # noqa: E402
import group_bank as GB  # noqa: E402

RUNS = os.path.join(YH, "llm_workbench", "data", "runs")


def latest(pat):
    hits = sorted(glob.glob(os.path.join(RUNS, pat)))
    return hits[-1] if hits else None


def rejudge(path, bank):
    d = json.load(io.open(path, encoding="utf-8"))
    ok2, fails, gate = 0, [], []
    for r in d["results"]:
        e = bank.by_id(r["id"])
        if not e:
            continue
        good, why = PB.verify(e, r.get("answer") or "", tuple(r.get("called") or []))
        ok2 += bool(good)
        if not good:
            fails.append(r["id"])
            if (bank is GB and e.get("gate")) or (bank is PB and PB.is_gate(e)):
                gate.append(r["id"])
    return d, ok2, fails, gate


print("判据 v%s" % PB.JUDGE_VERSION, flush=True)
for tag, pat, bank in (("v9t6-56", "*persona56_flow_cold.json", PB),
                       ("v9t7-56", "*persona56_v9t7_56.json", PB),
                       ("v9t6-group", "*group_v9t6_group_cpu.json", GB),
                       ("v9t7-group", "*group_v9t7_group.json", GB)):
    p = latest(pat)
    if not p:
        print("%-11s 没有记录" % tag)
        continue
    d, ok, fails, gate = rejudge(p, bank)
    print("%-11s %2d/%d | 闸门 %s | 失败 %s"
          % (tag, ok, d["total"], ("✗ " + ",".join(gate)) if gate else "过", ",".join(fails)))

print("\n=== v9t7 关键题的原始回答 ===", flush=True)
p = latest("*persona56_v9t7_56.json")
if p:
    d = json.load(io.open(p, encoding="utf-8"))
    for r in d["results"]:
        if r["id"] in ("s06", "p06", "p10", "st02"):
            print("  [56] %-4s %r" % (r["id"], (r.get("answer") or "")[:90]))
p = latest("*group_v9t7_group.json")
if p:
    d = json.load(io.open(p, encoding="utf-8"))
    for r in d["results"]:
        if r["id"] in ("g14", "g18", "g25", "g03", "g09"):
            print("  [群] %-4s %r" % (r["id"], (r.get("answer") or "")[:90]))
