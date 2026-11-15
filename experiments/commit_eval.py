# -*- coding: utf-8 -*-
"""提交一键评测。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_eval.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(workbench): 一键评测——工作站第一片收口\n\n"
    "backend/eval_runner.py\n"
    "- start(tag)：起 experiments/eval56_28.py --provider cloud（152+75，约4分钟、约¥2.5）\n"
    "  状态写 cache/eval_state.json，日志 cache/logs/eval_<tag>.log\n"
    "- status()：running / 结果（人格与群聊分数、失败项 id）/ 日志尾\n"
    "- history(n)：扫描 cache/eval_*.json，给最近几轮对比\n\n"
    "接口：GET /api/eval_status、POST /api/eval_run\n"
    "卡：一键评测（跑一轮 + 当前状态 + 结果 + 最近几轮）\n\n"
    "两个路由坑（都写进注释了）\n"
    "- daemon 的 do_POST 把所有 /api/* 转给 console_server → 必须给 eval_run 开例外\n"
    "- GET 侧同理（stack_status/qq_intel/recent_turns/eval_status 都在 daemon 侧直拦）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-120:])
