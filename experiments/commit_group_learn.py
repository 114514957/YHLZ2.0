# -*- coding: utf-8 -*-
"""提交群聊学习（情报注入 + 学习作业）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_group_learn.txt")
L = [
    "feat(qq): 群聊学习——情报注入 + 学习作业（老爹果「群聊才是学习的关键」）",
    "",
    "① 群情报注入（backend/target_entry.py 群分支）",
    "   - 之前 qq_intel.card_text() 已能算「人数/活跃/话题/Top成员/@她次数」，但没接线",
    "   - 现在每个群回合注入 ≤300 字情报卡（YHLZ_QQ_INTEL_DEBUG=1 可打日志）",
    "   - 验证：问「这群最活跃的三个人是谁」→ 答「六哉喵喵、霄、蒙觊sama」，",
    "     与情报卡完全一致（这是聚合数据，只有卡能提供）",
    "",
    "② 群聊学习作业 tools/group_learn.py",
    "   - 从 qq_social_* 产出三类知识：群观察 / 群话题 / 群人物（每人：发言量、@她次数、常聊话题）",
    "   - 写进知识库（category 区分），**不塞她的个人记忆**——避免像今天审计发现的",
    "     「L2 里 70% 是工程流水账」那样被污染",
    "   - 实跑：写入 22/22（群观察 3、群话题 3、群人物 16）；kb_query 能查回",
    "",
    "遗留：kb_list/kb_query 的 category 过滤似乎未生效（返回不分类的结果），待查。",
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
