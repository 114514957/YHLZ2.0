# -*- coding: utf-8 -*-
"""提交「场景裁剪」实现（默认关闭）+ 三实验对照证据。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_scene.txt")
L = [
    "feat(prompt): 场景裁剪（闲聊只发必要块）——默认关闭，群聊版待定",
    "",
    "老爹的判断：聊天不需要全部提示词，只要人格与禁令。已实现两档：",
    "  · 全局 casual 裁剪：私聊 3529→2521（-29%）、公开 3903→3198",
    "  · 只裁群聊（public）：私聊不变、群聊 3903→3198（-18%）",
    "",
    "三次实验的一致形状（各 3 轮或 2 轮，云端 152+75）",
    "  工具 43→6      ：私聊 -7、群聊 +1~2、省 35% token",
    "  提示词压缩 -13%：私聊 -5、群聊 +3",
    "  整块裁剪 -29%  ：私聊 -10、群聊 +2~3",
    "  只裁群聊       ：私聊 122/120（提示词未变，疑噪声）、群聊 75/74",
    "",
    "结论：**她的人格靠整包指导撑着，私聊不能减；群聊要的正是短与不反问，减了更好。**",
    "默认关闭（YHLZ_PROMPT_SCENE=1 才生效），等老爹决定是否只对群聊开。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-100:])
