# -*- coding: utf-8 -*-
"""由 v9t8 的脚本派生 v9t10 的收尾/评测脚本（字符串替换，避免手抄出错）。"""
from __future__ import annotations

import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WB = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench"

for src, dst in (("finish_v9t8.py", "finish_v9t10.py"),
                 ("eval_v9t8.py", "eval_v9t10.py")):
    s = io.open("%s\\%s" % (WB, src), encoding="utf-8").read()
    s = s.replace("v9t8", "v9t10")
    io.open("%s\\%s" % (WB, dst), "w", encoding="utf-8").write(s)
    print("写出 %s（%d 字节，含 v9t10 出现 %d 次）" % (dst, len(s), s.count("v9t10")))
