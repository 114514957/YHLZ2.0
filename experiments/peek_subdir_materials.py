# -*- coding: utf-8 -*-
"""看子目录那几大批是什么：外部开源语料，还是自家生成/改写。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")

FILES = [
    r"_待定\开源对话样本_扩充19k_20261021.md",
    r"_待定\开源对话样本_补speaking_20261021.md",
    r"_草稿\个性生成_1021_203543_0-300.md",
    r"_修订\对话样本_风格重做版_20261018.md",
]

for rel in FILES:
    p = os.path.join(MAT, rel)
    if not os.path.exists(p):
        print("缺：%s" % rel)
        continue
    t = io.open(p, encoding="utf-8", errors="replace").read()
    print("=" * 70)
    print("%s（%.1f MB）" % (rel, os.path.getsize(p) / 1e6))
    print("--- 头 700 字 ---")
    print(t[:700])
    print()
