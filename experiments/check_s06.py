# -*- coding: utf-8 -*-
"""查 base-f12 这两次跑的 s06 原始回答（判据过 ≠ 真拒了）。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"

hits = [p for p in glob.glob(os.path.join(RUNS, "*.json")) if "base-f12" in p]
print("找到 %d 份：%s" % (len(hits), [os.path.basename(h) for h in hits]))
for p in sorted(hits):
    d = json.load(io.open(p, encoding="utf-8"))
    if d.get("suite") != "persona56":
        continue
    print("\n== %s（%s）" % (os.path.basename(p), d.get("tag")))
    for r in d.get("results", []):
        if r["id"] in ("s06", "r07", "r08"):
            print("  %-4s ok=%-5s %r" % (r["id"], r.get("ok"), (r.get("answer") or "")[:60]))
