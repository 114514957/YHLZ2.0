# -*- coding: utf-8 -*-
"""规整 .gitignore：清掉重复的实验站块，只保留一份；可重复运行（幂等）。

历史：最早用 cmd echo 追加中文，写成了 GBK，把文件编码搞坏；
后来改成按行截断重写，但每跑一次就多追加一块（实测叠到 3 块）。
现在改成：先删掉所有已有的块，再追加一份。
"""
from __future__ import annotations

import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\.gitignore"

MARK = "# 实验站运行时日志与版本产物目录（含 adapter/gguf/tar 大文件，不入库）"
RULES = [
    "experiments/runs/server_*.log",
    "experiments/runs/probe_*.log",
    "dist/v9t7_产物/",
    "dist/v9t8_产物/",
]

raw = open(P, "rb").read().decode("utf-8")     # 现在必须是合法 UTF-8
lines = [ln.rstrip() for ln in raw.splitlines()]

kept, removed = [], 0
for ln in lines:
    if ln == MARK or ln in RULES:
        removed += 1
        continue
    kept.append(ln)

while kept and kept[-1] == "":
    kept.pop()

out = kept + ["", MARK] + RULES
with io.open(P, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(out) + "\n")

print("清理 %d 行重复块；现 %d 行，末尾一块：%s" % (removed, len(out), RULES[-2:]))
