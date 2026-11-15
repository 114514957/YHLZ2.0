# -*- coding: utf-8 -*-
"""把策划书 §6 的子小节重排成正确顺序与编号（之前插入时打乱了）。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "docs", "方案", "转向策划_封存小模型_接入大模型_工作台_20261115.md")
t = io.open(P, encoding="utf-8").read()

head, rest = t.split("## 6. 老爹已定的九件事", 1)
# rest 从"（2026-11-15 答复...）"开始，先切出 §6 引子（到第一个 ### 之前）
m = re.search(r"\n### ", rest)
intro = rest[:m.start()] if m else rest
body = rest[m.start():] if m else ""

# 按 ### 切块
blocks = re.split(r"\n(?=### )", body)
title_of = lambda b: b.splitlines()[0].strip()


def pick(keyword: str) -> str:
    for b in blocks:
        if not b.strip():
            continue
        head_line = b.splitlines()[0].strip() if b.splitlines() else ""
        if keyword in head_line:
            return b.rstrip() + "\n"
    raise SystemExit("找不到小节：%s" % keyword)


items = [
    ("6.1", "工作站最终版图"),
    ("6.2", "台账分家"),
    ("6.3", "记忆块继承"),      # 标题丢了，这里重建
    ("6.4", "阶段 1.5 · 记忆修整"),
    ("6.5", "形象区与记忆星图"),
    ("6.6", "提示词要参考的开源工程"),
    ("6.7", "记忆星图的数据基础"),
]

out = [head.rstrip() + "\n", "## 6. 老爹已定的九件事" + intro.rstrip() + "\n\n"]
for num, key in items:
    try:
        blk = pick(key)
    except SystemExit:
        if key == "记忆块继承":
            blk = ("### 6.3 记忆块继承（老爹新任务：**尝试继承之前的记忆块**）\n\n"
                   "> 本节正文见 §6.4 的现状实测；此处保留标题以免编号断层。\n\n")
        else:
            raise
    # 重写标题编号与名称
    lines = blk.splitlines()
    first = lines[0]
    # 取原标题里的说明部分（括号内）保留
    m2 = re.search(r"（(.*)）\s*$", first)
    tail = ("（" + m2.group(1) + "）") if m2 else ""
    new_first = "### %s %s%s" % (num, key, tail)
    out.append("\n".join([new_first] + lines[1:]).rstrip() + "\n\n")

io.open(P, "w", encoding="utf-8").write("".join(out))

print("重排完成，当前小节：")
for ln in io.open(P, encoding="utf-8").read().splitlines():
    if ln.startswith("### 6."):
        print("   " + ln)
