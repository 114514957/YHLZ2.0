# -*- coding: utf-8 -*-
"""回退块级试验1（SELF_MODEL 里那句展开），回到 B 版。"""
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
n = t.count(ADD)
t = t.replace(ADD, "")
io.open(P, "w", encoding="utf-8").write(t)
print("已回退 %d 处，回到 B 版（群聊硬规则 + SELF_MODEL 原样）" % n)
