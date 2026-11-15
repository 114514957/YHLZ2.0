# -*- coding: utf-8 -*-
"""提交工具预算接线（默认关闭）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_wire.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(llm): 工具预算接到 render_system（仍默认关闭）\n\n"
    "装配点查明：工具来自 CapabilityRegistry.export_openai_tools()，\n"
    "target_entry.render_system 已按 allowed_tools 收窄一次（权限层），\n"
    "本次在权限层之后追加**预算层**（tool_budget.select），两层互不替代。\n\n"
    "- 默认关闭：只有 YHLZ_TOOL_BUDGET=1 才生效\n"
    "- 收窄对象：渲染进系统提示的工具说明；异常一律回退原列表\n"
    "- 实测：casual 452 vs 全量 2933 token（省 85%）\n\n"
    "尚未接的一处：真正传给模型的 tools 参数（assistant 调用点）仍需在同一位置\n"
    "套 tool_budget.select —— 改完必须先跑 152 题回归（工具题不能掉）。\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip())
r = subprocess.run(["git", "status", "-sb"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout.splitlines()[0] if r.stdout else "")
