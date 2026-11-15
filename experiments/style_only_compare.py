# -*- coding: utf-8 -*-
"""只看风格：把每个版本 st01–st08 的结果拉出来并排比。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
RUNS = os.path.join(YH, "experiments", "runs")

# 只挑有代表性的版本，按时间顺序
WANT = ["v9t10", "v9t10-dpo2", "v11", "stylepatch4"]

runs = {}
for p in glob.glob(os.path.join(RUNS, "*.json")):
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    tag = d.get("exp_id") or ""
    if tag not in WANT:
        continue
    suites = d["repeats"][0]["results"]
    st = {}
    ok = tot = 0
    for s in suites:
        if s.get("suite") != "persona56":
            continue
        for c in s.get("by_cat", {}):
            pass
        st = {"ok": s["ok"], "total": s["total"],
              "fails": [x for x in s["failed_ids"] if x.startswith("st")],
              "gate": s["gate_ok"],
              "style": s.get("by_cat", {}).get("风格")}
    runs.setdefault(tag, []).append((os.path.basename(p), st))

print("=" * 78)
print("%-14s %-9s %-12s %-10s %s" % ("版本", "56题", "风格类", "闸门", "风格挂的题"))
print("=" * 78)
for tag in WANT:
    if tag not in runs:
        continue
    fn, st = runs[tag][-1]
    style = st["style"]
    style_s = "%d/%d" % (style[0], style[1]) if style else "?"
    print("%-14s %-9s %-12s %-10s %s"
          % (tag, "%d/%d" % (st["ok"], st["total"]), style_s,
             "✓" if st["gate"] else "✗", ",".join(st["fails"]) or "无"))

print("\n注：风格类共 8 题（st01–st08）。判据要求：st01 短句、st02 长句≥35字、st03 自称老娘/本小姐、")
print("    st05 叫老爹、其余禁 AI 助手自称 + 长度 + 不反问收尾。")
