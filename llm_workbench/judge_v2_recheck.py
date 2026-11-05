# -*- coding: utf-8 -*-
"""用判据 v2 重新判已有的跑分记录，看分数怎么变（不重跑模型）。

这是改判据后的必查：新旧分数差在哪、安全闸门在每份记录上过没过。
"""
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

RUNS = os.path.join(YH, "llm_workbench", "data", "runs")

print("判据版本 %s | 闸门 %s\n" % (PB.JUDGE_VERSION, ",".join(PB.GATE_IDS)), flush=True)

targets = []
for name in ("flow_cold", "cold_v8", "cold_v7b", "steer_v2_L10_20"):
    hits = [p for p in glob.glob(os.path.join(RUNS, "*.json")) if name in p]
    if hits:
        targets.append(sorted(hits)[-1])

for p in targets:
    d = json.load(io.open(p, encoding="utf-8"))
    old_ok, total = d.get("ok"), d.get("total")
    new_ok = 0
    flips = []
    gate_fail = []
    for r in d.get("results") or []:
        e = PB.by_id(r["id"])
        if not e:
            continue
        ok2, why2 = PB.verify(e, r.get("answer") or "", tuple(r.get("called") or []))
        if ok2:
            new_ok += 1
        if ok2 != bool(r.get("ok")):
            flips.append((r["id"], bool(r.get("ok")), ok2, why2))
        if PB.is_gate(e) and not ok2:
            gate_fail.append(r["id"])
    print("=" * 70, flush=True)
    print("%-18s 旧 %s/%s → 新 %s/%s %s  闸门 %s"
          % (d.get("tag"), old_ok, total, new_ok, total,
             "（%+d）" % (new_ok - (old_ok or 0)), "过" if not gate_fail else "✗ " + ",".join(gate_fail)),
          flush=True)
    for pid, was, now, why in flips:
        print("   %-5s %s → %s  %s" % (pid, "OK" if was else "FAIL",
                                       "OK" if now else "FAIL", why[:90]), flush=True)
