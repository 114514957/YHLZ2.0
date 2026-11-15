# -*- coding: utf-8 -*-
"""提交群聊硬规则 + 云端评测器 + 三版实验记录。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_group.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(prompt): 群聊硬规则（云端评测 65→75 满分）+ 评测器支持云端\n\n"
    "1) experiments/eval56_28.py 新增 --provider cloud（等价 --port 0），走 llm_router；\n"
    "   判分规则与题库一字未动 → 换大模型后仍可比。\n"
    "2) backend/target_prompts.py 新增 GROUP_HARD_RULES，只加在公开分支：\n"
    "   ≤60 字 / 不许反问收尾 / 不许 Markdown / 不许说自己跑在哪。\n\n"
    "三版对照（同题库、temperature 0、确定性判分）\n"
    "  A 原始            人格 128 / 群聊 65\n"
    "  B +群聊硬规则      人格 121 / 群聊 75（满分）\n"
    "  C B+私聊展开       人格 116 / 群聊 71  ← 两套都差，已回退\n\n"
    "结论：群聊硬规则治住了 10 道失败（6 道过长+Markdown、2 道反问、2 道泄露内部）；\n"
    "但\"放开/展开\"这类全局语气调整会污染短答题（C 的教训），\n"
    "人格要按块微调（把思辨类展开写进 SELF_MODEL/VOICE_ANCHOR 正文），不能全局加条款。\n\n"
    "当前停在 B：人格 121 / 群聊 75。\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
for args in (["git", "log", "--oneline", "-1"], ["git", "status", "-sb"]):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(r.stdout.splitlines()[0] if r.stdout else "")
