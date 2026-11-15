# -*- coding: utf-8 -*-
"""核实评测协议：题量、采样参数、判分、闸门定义。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

FILES = [
    ("experiments/accept_three_tracks.py", 40),
    ("tools/scorer_v2.py", 30),
]
for rel, n in FILES:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        print("缺 %s" % rel)
        continue
    t = io.open(p, encoding="utf-8", errors="replace").read()
    lines = t.splitlines()
    print("=" * 70)
    print("### %s（%d 行）" % (rel, len(lines)))
    pat = (r"temperature|top_p|max_tokens|greedy|seed|56|28|gate|闸门|threshold|"
           r"判分|judge|score|pass|r0\d|g0\d|PASS|FAIL|json")
    shown = 0
    for i, ln in enumerate(lines):
        if re.search(pat, ln) and len(ln.strip()) > 3:
            print("   %4d  %s" % (i + 1, ln.strip()[:116]))
            shown += 1
            if shown >= n:
                break
