# -*- coding: utf-8 -*-
"""看锚点那轮失败在哪：是"过度收敛/过度拒绝"还是别的原因。"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

for tag in ("基线b_带工具", "锚点"):
    p = os.path.join(ROOT, "cache", "eval_%s.json" % tag)
    d = json.load(open(p, encoding="utf-8"))
    print("=" * 74)
    print("### %s：56 %s｜28 %s" % (tag, d["summary"]["persona"], d["summary"]["group"]))
    keys = set(d["summary"]["group_fail"]) | set(d["summary"]["persona_fail"])
    for suite in ("group", "persona"):
        for r in d["detail"][suite]:
            if r["id"] in keys:
                print("  [%s] %s ok=%s why=%s" % (suite, r["id"], r["ok"],
                                                  str(r["why"])[:60]))
                print("     答：%s" % str(r["ans"]).replace("\n", " ")[:110])
