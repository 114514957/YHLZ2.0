# -*- coding: utf-8 -*-
"""验覆盖层：改一块 → 渲染反映 → 还原。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

from backend import prompt_overrides as P  # noqa: E402

base = P.preview(False)
print("默认：%d 字｜改动块 %d" % (base["chars"], P.status()["count_changed"]))

print("\n① 改 STYLE_HABIT_CLAUSE")
r = P.set_block("STYLE_HABIT_CLAUSE", "（测试覆盖）被问到家了就答『回来了』。")
print("   ", r)
p = P.preview(False)
print("   → 渲染 %d 字｜含覆盖文本：%s" % (p["chars"], "测试覆盖" in p["text"]))

print("\n② 非法块名")
print("   ", P.set_block("TARGET_SYSTEM_PROMPT", "x"))

print("\n③ 超长拒绝（4001 字）")
print("   ", P.set_block("CONCISE_CLAUSE", "字" * 4001))

print("\n④ 还原")
print("   ", P.set_block("STYLE_HABIT_CLAUSE", ""))
p = P.preview(False)
print("   → 渲染 %d 字｜残留覆盖：%s｜改动块 %d"
      % (p["chars"], "测试覆盖" in p["text"], P.status()["count_changed"]))
