# -*- coding: utf-8 -*-
"""回退 PRIVATE_ELABORATION_CLAUSE（实测 128/65 → 121/75 → 116/71，这条让两套都更差）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P, encoding="utf-8").read()

i = t.find("PRIVATE_ELABORATION_CLAUSE = ")
if i > 0:
    start = t.rfind("\n# 2026-11-15（台账 1246）", 0, i)
    end = t.find('"""', t.find('"""', i) + 3) + 3
    t = t[:start] + t[end:]

old = ("    if public:\n        blocks.append(GROUP_HARD_RULES)\n"
       "    else:\n        blocks.append(PRIVATE_ELABORATION_CLAUSE)\n")
new = "    if public:\n        blocks.append(GROUP_HARD_RULES)\n"
if old in t:
    t = t.replace(old, new, 1)

io.open(P, "w", encoding="utf-8").write(t)
print("已回退私聊展开条款；保留群聊硬规则")
