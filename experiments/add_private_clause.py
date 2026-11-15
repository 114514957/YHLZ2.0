# -*- coding: utf-8 -*-
"""私聊加"该展开就展开"的反向约束（群聊硬规则造成人格 -7 的对冲）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P, encoding="utf-8").read()

CLAUSE = '''
# 2026-11-15（台账 1246）：群聊硬规则（≤60 字）把私聊的思辨题也压扁了，
# 实测人格套 128→121（p25/p31/p33/p54、st16/st18 全是该展开的题）。
# 这段只加在私聊/非公开分支，给回展开空间。
PRIVATE_ELABORATION_CLAUSE = """【私聊该展开就展开】
群聊那套"一句两句、不超过 60 字"的硬规矩，在私聊里不适用。
老爹认真问想法时（为什么、你怎么看、讲讲故事、回忆某件事），要把话说完：两三个短句写到一小段，
别为了短而少说一层意思。仍然不许破折号、不许"不是A而是B"的对称句、不许反问收尾。"""
'''

anchor = "\nGROUP_HARD_RULES = "
assert t.count(anchor) == 1
t = t.replace(anchor, CLAUSE + anchor, 1)

old = "    if public:\n        blocks.append(GROUP_HARD_RULES)\n"
new = ("    if public:\n        blocks.append(GROUP_HARD_RULES)\n"
       "    else:\n        blocks.append(PRIVATE_ELABORATION_CLAUSE)\n")
assert t.count(old) == 1, "找不到插入点"
t = t.replace(old, new, 1)

io.open(P, "w", encoding="utf-8").write(t)
print("已加 PRIVATE_ELABORATION_CLAUSE 并接进非公开分支")
