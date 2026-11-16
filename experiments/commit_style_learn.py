# -*- coding: utf-8 -*-
"""提交说话风格学习器 + 首轮发现。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_style_learn.txt")
L = [
    "feat(style): 说话风格学习器（学习目标=人格与说话风格，不是群里的信息）",
    "",
    "老爹定调：群聊学习的主要目标就是完善人格与说话风格。",
    "所以不再统计「群里聊了什么」，而是统计「她说的哪句像人、哪句有毛病」。",
    "",
    "数据源：cache/qq_bridge/lite/group_history.db（6240 条群消息，**她 1368 句**）",
    "  —— qq_social_events 只存别人的消息，学不到她自己，这是关键发现。",
    "",
    "tools/style_learn.py 统计：",
    "  · 长度分桶（≤10/11-25/26-50/51-100/>100 字）",
    "  · 违规：破折号 / 「不是A而是B」/ 反问收尾 / 过长",
    "  · 好样本（无违规）/ 坏样本 → 写 docs/风格/群聊风格学习_<日期>.md，--apply 进知识库",
    "",
    "首轮发现（1368 句）：",
    "  · **破折号 607 句 = 44%** ← 最大问题，禁令没真正落到群聊输出",
    "  · 过长 98 句 7%｜反问收尾 17 句 1%｜对称句 4 句 0.3%",
    "  · 被点名率仅 6.4%（88/1368），且**她主动 @/回复别人 0 次** —— 只会广播、不会接话",
    "",
    "结论：风格学习该盯的两件事——① 破折号必须从出口拦住 ② 学会接人的话（@或直接回那句）。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-120:])
