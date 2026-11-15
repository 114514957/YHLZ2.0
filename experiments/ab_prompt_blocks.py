# -*- coding: utf-8 -*-
"""A/B：今天新加的两个提示块（相处与表达 / 说话硬规则）到底让分数升还是降。

做法：用工作台覆盖接口把两块临时置空 → 跑 56+28 → 还原 → 与今天基线（45/56、28/28）比。
不动代码、不重启 daemon（渲染每轮现做）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
BASE = "http://127.0.0.1:8321"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=30) as r:
        return json.loads(r.read().decode())


def preview_chars() -> int:
    with OPENER.open(BASE + "/prompt/preview?public=0", timeout=20) as r:
        return json.loads(r.read().decode())["chars"]


print("当前提示词字数：%d" % preview_chars())

# 置空两块（一个空格，等于这块什么都不说，但保留渲染结构）
for key in ("SOCIAL_POSTURE_CLAUSE", "VOICE_HARD_RULES"):
    print("  置空 %-22s → %s" % (key, post("/prompt/set", {"key": key, "text": " "})))
print("置空后字数：%d" % preview_chars())

try:
    r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "experiments", "eval56_28.py"),
                        "--tag", "无新块", "--port", "8081"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "")[-900:])
finally:
    for key in ("SOCIAL_POSTURE_CLAUSE", "VOICE_HARD_RULES"):
        post("/prompt/set", {"key": key, "text": ""})   # 空 = 恢复默认
    print("已还原两块；字数回到 %d" % preview_chars())
