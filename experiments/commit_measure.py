# -*- coding: utf-8 -*-
"""提交度量工具与结论。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_measure.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(llm): token 度量工具（为瘦身提供数据，不猜）\n\n"
    "tools/measure_llm_tokens.py：按块拆系统提示、按个拆工具 schema。\n\n"
    "实测（私聊系统提示 + 43 工具）：\n"
    "- 系统提示 5009 字 / 3489 token（16 块）\n"
    "- 工具 43 个 / 2933 token（均值 68；最大 schedule_plan 161）\n"
    "- 一句「在吗」共 6039 token → 系统 3489 + 工具/历史 ~2550\n\n"
    "关键发现：STYLE_PACK_FINAL / FINAL2、VOICE_ANCHOR_FINAL / FINAL2 等 11 个常量\n"
    "**并未被渲染**（死重量，不花 token），所以真正的省钱点在\n"
    "① 工具按需加载（2933 → 约 600，可省 75%）② 16 个块合并同类（预计省 800–1000）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-100:]))
r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip())
