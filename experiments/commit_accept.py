# -*- coding: utf-8 -*-
"""提交 401 修复 + 三渠道验收记录。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_accept.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "fix(qq): /turn 路径凭证为空导致 401（三渠道验收时发现）\n\n"
    "现象：按桥的格式打 /turn（channel=qq_p2258374446, source=qq_bridge）→\n"
    "  私聊 401 Authorization Required\n"
    "  群聊 550 Response Reset by EdgeOne（上游抖动）\n\n"
    "根因：daemon 自己建 llm 时写死 api_key=\"\"（base_url=LOCAL_BASE, model=LOCAL_MODEL）\n"
    "修法：改为 _llm_endpoint()[\"api_key\"]；全文件已无 api_key 空串\n\n"
    "验收结果（daemon 侧，按桥的真实通道格式）\n"
    "  qq_p2258374446  私聊 → 「在。」20.3s\n"
    "  qq_g1121723665  群聊 → 「在。」5.7s\n"
    "  记账：factory deepseek-chat in=6822/6906 out=28\n"
    "  召回：qq_g1121723665 n=2（群通道召回也在跑）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-110:])
