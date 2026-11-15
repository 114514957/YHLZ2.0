# -*- coding: utf-8 -*-
"""用消息文件提交，避免长中文 message 在 cmd 里被拆坏（/talk 又被当成路径了）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_401.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "fix(llm): 修 401——密钥无条件解析，target_entry 不写死空 api_key\n\n"
    "两个坑（实测）：\n"
    "1) 工厂只在 base_url/model 均为 None 时解析密钥；daemon 传显式 base_url（已解析成\n"
    "   云端地址）→ key 为空 → 401 Authorization Required\n"
    "2) target_entry 7 处调用写死 api_key=\"\" → 同样 401\n\n"
    "另外：daemon 流式路原先只读环境变量（密钥在 config/llm.local.json），改走 llm_endpoint；\n"
    "_try_cloud 用解析出的 model，不再写死 gemma-4-e4b。\n\n"
    "验证：daemon 流式回「在。」5.1 秒，无 401（云端 deepseek-chat）。\n"
    "遗留：流式路径尚未记账（需在 llm_stream 抓 usage）。\n")

for cmd in (["git", "add", "-A"],
            ["git", "commit", "-q", "-F", MSG],
            ["git", "-c", "http.proxy=", "-c", "https.proxy=", "push", "origin", "main"]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d" % (" ".join(cmd[:2]), r.returncode))
    if r.stdout.strip():
        print("  " + r.stdout.strip()[-200:])
    if r.returncode != 0 and r.stderr.strip():
        print("  stderr: " + r.stderr.strip()[-200:])

r = subprocess.run(["git", "log", "--oneline", "-2"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout)
