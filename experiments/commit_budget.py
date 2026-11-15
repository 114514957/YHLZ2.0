# -*- coding: utf-8 -*-
"""提交工具预算接线（默认关闭）+ 3 轮评测证据（用「」避免中文引号）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_budget.txt")
L = [
    "feat(llm): 工具按需加载接到真正的 tools= 传参点（默认关闭，实测不达标）",
    "",
    "接线点：target_orchestrator.run() 里 `tools = self._export_tools()` 之后",
    "（靠「数数量」定位到的真正传参点，之前一直找错层）。",
    "评测器也加了同款过滤（环境变量开时生效），否则测不到「少给工具」的影响。",
    "",
    "实测（各 3 轮，云端 152+75）",
    "  预算关：人格 126 / 126 / 121（中位 126）｜群聊 72 / 71",
    "  预算开：人格 121 / 119 / 119（中位 119）｜群聊 73 / 73 / 74",
    "  → 人格 -7（超出噪声）、群聊 +1~2、工具题稳定多挂 2 道（t12/t17/t32）",
    "  → 单轮输入 token：6837 → 4297（-35%，省钱是真的）",
    "",
    "结论：**质量代价大于收益，默认保持关闭**（YHLZ_TOOL_BUDGET=1 才开）。",
    "机制猜测：工具给少了，她更「话多」，而人格题大量是短句类 → 掉分。",
    "后续方向：① 只对群通道开（群聊反而 +）；② 改做提示词瘦身（3.5k→1.5k）。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-70:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-110:])
