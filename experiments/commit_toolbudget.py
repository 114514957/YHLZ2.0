# -*- coding: utf-8 -*-
"""提交工具预算模块。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_toolbudget.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(llm): 工具按需加载选择器（默认关闭，未接线）\n\n"
    "背景（台账 1242）：43 个工具 schema = 2933 token，每轮全塞，\n"
    "而一句「在吗」实测总 6039 token，工具占约一半。\n\n"
    "backend/tool_budget.py\n"
    "- 三档：casual(6 个核心) / normal(+检索 10 个) / work(全量)\n"
    "- 判断：工程词表 → work；检索/回忆词 → normal；其余 → casual\n"
    "- 安全兜底：未启用、异常、裁到空 → 一律回退全量（宁可多花钱，不让它没工具用）\n"
    "- 默认关闭（YHLZ_TOOL_BUDGET=1 才生效）——接线前要先过 152 题回归\n\n"
    "实测（本机 tokenizer）\n"
    "  全量 2933 token｜casual 452（省 85%）｜work 2933\n\n"
    "backend/test_tool_budget.py：9 项单测全过（分档/禁用/权限收窄/不裁空/省 token）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-90:]))
r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip())
