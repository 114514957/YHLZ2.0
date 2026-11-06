# -*- coding: utf-8 -*-
"""把所有实验记录并成一张表（station 的 table 命令的雏形）。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")

rows = []
for p in sorted(glob.glob(os.path.join(RUNS, "*.json"))):
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    if not d.get("repeats"):
        continue
    r = d["repeats"][0]["results"]
    def g(suite, key, default=None):
        for x in r:
            if x["suite"] == suite:
                return x.get(key, default)
        return default
    rows.append({
        "exp": d.get("exp_id"),
        "at": d.get("started_at", "")[5:16],
        "backend": d.get("backend"),
        "judge": d.get("judge_version"),
        "p56": "%s/%s" % (g("persona56", "ok"), g("persona56", "total")),
        "p56_gate": "过" if g("persona56", "gate_ok") else "✗",
        "grp": "%s/%s" % (g("group", "ok"), g("group", "total")),
        "grp_gate": ("过" if g("group", "gate_ok") else "✗") if g("group", "total") else "-",
        "p56_fail": ",".join((g("persona56", "failed_ids") or []))[:70],
    })

print("%-10s %-12s %-5s %-10s %-8s %-10s %s"
      % ("实验", "时间", "后端", "56题", "闸门", "群聊", "56 题失败"))
for r in rows:
    print("%-10s %-12s %-5s %-10s %-8s %s/%s%s"
          % (r["exp"], r["at"], r["backend"], r["p56"], r["p56_gate"],
             r["grp"], r["grp_gate"].replace("过", "").replace("✗", "✗"),
             ""))
print()
for r in rows:
    print("%-10s 56失败: %s" % (r["exp"], r["p56_fail"]))
