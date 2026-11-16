# -*- coding: utf-8 -*-
"""提交记忆/时刻度验证脚本与结果。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_verify.txt")
L = [
    "test: 记忆与时刻度的端到端验证（9/9 通过，不是花瓶）",
    "",
    "老爹：「验证记忆，时刻度，别做了几个花瓶出来」",
    "",
    "① 记忆验证（生产路径，造暗号）",
    "   - 插入唯一暗号记忆「青柠七号」（她不可能靠常识知道）→ 重建索引 → 重启 daemon",
    "   - 问「老爹的验证暗号是什么」→ 答「青柠七号。」✅",
    "   - recall_trace 里近 5 分钟注入 ids 含 verify_memory_* ✅（证明是召回注入，不是猜）",
    "   - 反例：「我的车是什么颜色的」→「我这边查不到你车的颜色，记忆里没有这条。」✅ 不编造",
    "   - 测完删除测试记忆 + 重建索引 + 重启，不留污染",
    "",
    "② 时刻度验证",
    "   - 无未来时间戳（最新 11-15 23:34）｜6240/6240 有 at｜同群随 seq 单调（逆序 0）",
    "   - 从 DB 现算复现因果：清洗前 47.0%（1292 句）、清洗后 0.0%（76 句）",
    "   - 噪声前提：13 天，最少 45 句/天，中位 80 → 足以做按天趋势",
    "",
    "脚本 experiments/verify_memory_and_clock.py 可重跑（自带清理）。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-110:])
