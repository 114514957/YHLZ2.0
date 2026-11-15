# -*- coding: utf-8 -*-
"""给群聊/公开回复加硬约束（云端基线 65/75 → 目标 70+）。

依据云端基线失败原文（台账 1246 预备）：
  · 6 道过长（431/301/383 字 vs 限 160/140/180）＋ Markdown 加粗
  · 2 道反问收尾
  · 2 道泄露内部（"我跑在家里的主机上"、"住哪"）
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P, encoding="utf-8").read()

CLAUSE = '''
# 2026-11-15（台账 1246）：大模型在群聊里"太像助手"——实测 10 道失败里
# 6 道是太长+Markdown、2 道反问收尾、2 道泄露内部。这段是**硬约束**，放最后。
GROUP_HARD_RULES = """【群聊硬规则】
公开场合说话，四条不许破：
1. **短**。默认一两句、全句不超过 60 字。技术问题也只给一句结论＋"要细说我再展开"，不许一次铺开清单。
2. **不许反问收尾**。想追问就直说一句（"细说"、"贴报错"），别用"…？"把球抛回去。
3. **不许 Markdown**：不用 ** 加粗、不列编号、不点杠、不写标题。群里就是说话。
4. **不许说自己跑在哪**。机器、配置、显卡、模型大小、住的地址、模型参数——一律"这个不往外说"，然后转回能聊的。
技术问题先给结论，被夸就一句话接住，被骂可以对回去但不解释自己。"""
'''

anchor = '\nCRUTCH_BAN_CLAUSE = '
assert t.count(anchor) == 1, "定位失败：CRUTCH_BAN_CLAUSE"
t = t.replace(anchor, CLAUSE + anchor, 1)

# 在公开分支末尾追加（找 PUBLIC_TOOLS 渲染处之后）
old = '    else:\n        tools = [t for t in tools if t.get("function", {}).get("name") in PUBLIC_TOOLS]'
if old in t:
    t = t.replace(old, old, 1)  # 不在这个文件里，留给 target_entry

io.open(P, "w", encoding="utf-8").write(t)
print("已在 target_prompts.py 加 GROUP_HARD_RULES")
