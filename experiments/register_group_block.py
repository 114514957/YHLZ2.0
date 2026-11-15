# -*- coding: utf-8 -*-
"""把 GROUP_HARD_RULES 登记成可编辑块，并让渲染走覆盖（_ov）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① prompt_overrides.EDITABLE 里加一项
P1 = os.path.join(ROOT, "backend", "prompt_overrides.py")
t1 = io.open(P1, encoding="utf-8").read()
if '"GROUP_HARD_RULES"' not in t1:
    anchor = '    "VOICE_HARD_RULES": '
    i = t1.find(anchor)
    assert i > 0, "找不到 VOICE_HARD_RULES 条目"
    line_end = t1.find("\n", i)
    add = ('\n    "GROUP_HARD_RULES": "群聊硬规则（≤60字／不反问／禁Markdown／不说配置）",')
    t1 = t1[:line_end] + add + t1[line_end:]
    io.open(P1, "w", encoding="utf-8").write(t1)
    print("已登记 GROUP_HARD_RULES")
else:
    print("已登记过")

# ② 渲染时走 _ov（这样工作台的覆盖才会生效）
P2 = os.path.join(ROOT, "backend", "target_prompts.py")
t2 = io.open(P2, encoding="utf-8").read()
old = "        blocks.append(GROUP_HARD_RULES)"
new = '        blocks.append(_ov("GROUP_HARD_RULES", GROUP_HARD_RULES))'
if old in t2:
    t2 = t2.replace(old, new, 1)
    io.open(P2, "w", encoding="utf-8").write(t2)
    print("渲染已改为 _ov(GROUP_HARD_RULES)")
elif new in t2:
    print("渲染已是 _ov")
else:
    print("⚠ 没找到群聊硬规则的追加语句，请人工确认")
