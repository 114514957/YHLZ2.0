# -*- coding: utf-8 -*-
"""块级微调（第一块）：在 SELF_MODEL_CLAUSE 正文里加"思辨类要展开"。

为什么不全局加：C 版实测（台账 1246）全局"放开"会让两套同时掉。
这次只动**一块**，且只针对"问想法/为什么"的场景，短答场景不受影响。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P, encoding="utf-8").read()

ADD = ("\n问到你自己的想法（为什么、你怎么看、讲讲故事）时，把话说完整：两三个短句写到一小段，"
       "别为省字把一层意思吞掉；对方只是打个招呼、应一声，就照旧短。")

marker = "SELF_MODEL_CLAUSE = "
i = t.find(marker)
assert i > 0, "找不到 SELF_MODEL_CLAUSE"
# 找到该常量的结束三引号
q1 = t.find('"""', i)
q2 = t.find('"""', q1 + 3)
assert q1 > 0 and q2 > q1
seg = t[q1:q2]
assert ADD not in seg, "已经加过了"
t = t[:q2] + ADD + t[q2:]
io.open(P, "w", encoding="utf-8").write(t)
print("已在 SELF_MODEL_CLAUSE 末尾加一句（块级，不全局）")
