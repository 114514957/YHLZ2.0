# -*- coding: utf-8 -*-
"""提交瘦身实验（已回滚，只留脚本与证据）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_slim.txt")
L = [
    "exp(prompt): 提示词瘦身实验（13% token，验收不通过，已回滚）",
    "",
    "做法：把前 5 大块（1493 token）按「每条规则保留、只说一遍」重写压缩，",
    "走 override 写入（可秒回滚），系统提示 3489 → 3045 token（-444，-13%）。",
    "",
    "验收（3 轮云端 152+75）",
    "  基线（原提示词）：126 / 126 / 121（中位 126）｜群聊 72 / 71",
    "  瘦身后：        117 / 121 / 122（中位 121）｜群聊 74 / 75 / 75",
    "  → 人格 -5、群聊 +3；与「工具预算」实验结果**同一个形状**（私聊掉、群聊升）",
    "",
    "结论：不发布，已 restore_all 回滚（私聊系统提示回到 3489 token，overrides 清空）。",
    "洞察：任何「减少指导」的省钱手段，都会让私聊更松（掉人格题）、群聊更松（反而对），",
    "      因为群聊要的正是短与不反问。→ 若要用，只能**只对群通道**开。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-70:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-100:])
