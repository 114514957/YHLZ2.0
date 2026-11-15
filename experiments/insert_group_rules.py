# -*- coding: utf-8 -*-
"""把 GROUP_HARD_RULES 真正插进 render_system_prompt 的公开分支。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P, encoding="utf-8").read()

i = t.find("def render_system_prompt")
assert i > 0
m = re.search(r"\n    return ", t[i:])
assert m, "找不到 return"
pos = i + m.start()
ins = ('\n    # 2026-11-15（台账 1246）：群聊硬约束，只在公开分支加\n'
       '    if public:\n'
       '        blocks.append(GROUP_HARD_RULES)\n')
t = t[:pos] + ins + t[pos:]
io.open(P, "w", encoding="utf-8").write(t)
print("已插入公开分支")
