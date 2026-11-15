# -*- coding: utf-8 -*-
"""提交：群聊硬规则登记为可编辑块 + 最近回合卡。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_promptblock.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "fix(workbench): 群聊硬规则登记为可编辑块（26 块）+ 最近回合卡\n\n"
    "老爹问「提示词块呢」→ 查了工作台 /prompt/blocks：25 个可编辑块里**没有 GROUP_HARD_RULES**，\n"
    "和我 11-13 踩过的 VOICE_HARD_RULES 是同一个 bug：渲染用常量、登记表里没有 → 改不了。\n\n"
    "修法\n"
    "- prompt_overrides.EDITABLE 加 GROUP_HARD_RULES（现 26 块）\n"
    "- target_prompts 渲染改为 _ov(\"GROUP_HARD_RULES\", ...)，覆盖才生效\n"
    "- 验证：set → 公开提示 5455→5210 字且含测试文本 → reset → 回到 5455 字\n\n"
    "另新增「最近回合」卡（台账 1254）\n"
    "- backend/recent_turns.py：把 recall_trace 与 llm_usage 按时间并起来\n"
    "- GET /api/recent_turns?limit=N\n"
    "- 页面卡：问句 / 注入 n 条(ids) / in-out / 费用，20 秒刷新\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-90:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-140:])
