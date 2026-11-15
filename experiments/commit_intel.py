# -*- coding: utf-8 -*-
"""提交群情报卡。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_intel.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(qq): 群情报卡——人多但活跃的少，压成卡片\n\n"
    "老爹：qq群里人很多但实际上没多少人活跃，做精简情报卡。\n\n"
    "backend/qq_intel.py\n"
    "- group_cards()：每群 人数/活跃数/消息量/近7天/话题/Top成员(消息·占比·最近活跃·@她次数)\n"
    "- card_text()：≤300 字、可直接注入上下文的版本\n"
    "- 话题词用 jieba（未分词的中文 n-gram 全是\"我也/我这\"这类垃圾），jieba 缺失自动回退\n"
    "- 数据源：memstore 的 qq_social_people / qq_social_events / qq_social_edges\n\n"
    "实测（3 个群）\n"
    "  小寻虚拟主播交流群 54人(活跃18)/3141条/近7天54\n"
    "  AI对话 8人(活跃7)/1327条/近7天99\n"
    "  AI相关工程开发交流群 25人(活跃4)/248条/近7天2  ← 基本停了\n\n"
    "工作台：GET /api/qq_intel +「群情报」卡（每群一行 + Top3 主力）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-100:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-160:])
