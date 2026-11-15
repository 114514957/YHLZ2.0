# -*- coding: utf-8 -*-
"""给 build_bench_extra.py 打两个补丁：
  ① 风格题 id 从 s09..s21 改成 st09..st21（现有题库已用到 s10，撞车）
  ② 校验器认可 negative 作为内容约束（现有风格题就是 negative + max_len 组合）
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "tools", "build_bench_extra.py")
t = io.open(P, encoding="utf-8").read()
before = t

for i in range(9, 22):
    t = t.replace('("s%02d",' % i, '("st%02d",' % i)

t = t.replace(
    'if not keys and not e.get("expect_any_tool") and not e.get("forbid_tools"):',
    'if (not keys and not e.get("negative")\n'
    '                and not e.get("expect_any_tool") and not e.get("forbid_tools")):')
t = t.replace(
    'if e.get("max_len") and not keys:',
    'if e.get("max_len") and not keys and not e.get("negative"):')

io.open(P, "w", encoding="utf-8").write(t)
print("改动：%s" % ("有" if t != before else "无"))
print("风格题 id 现在：%s" % re.findall(r'\("(st\d\d)"', t))
