# -*- coding: utf-8 -*-
"""看 v9t10 群聊三道的原始回答，确认 g14 是不是判据误报。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")

hits = sorted(glob.glob(os.path.join(RUNS, "*group_v9t10_group.json")))
print("记录 %d 份" % len(hits))
d = json.load(io.open(hits[-1], encoding="utf-8"))
for r in d["results"]:
    if r["id"] in ("g11", "g13", "g14", "g18", "g09", "g03"):
        print("  %-4s ok=%-5s %r" % (r["id"], r.get("ok"), (r.get("answer") or "")[:70]))
        if not r.get("ok"):
            print("       why: %s" % r.get("why"))
