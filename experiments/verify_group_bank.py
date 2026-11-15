# -*- coding: utf-8 -*-
"""群聊题库的闸门与题号 + 评测脚本的采样参数。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

t = io.open(os.path.join(ROOT, "tools", "group_bank.py"),
            encoding="utf-8", errors="replace").read()
print("=== group_bank 闸门 ===")
for m in re.finditer(r"GATE[A-Z_]*\s*=\s*[^\n]+", t):
    print("   " + m.group(0)[:120])
ids = re.findall(r'"id":\s*"([a-z]\w+)"', t)
print("   题号：%s（共 %d）" % (ids[:32], len(ids)))

for rel in ("tools/v9_eval_local.py", "tools/v9_tool_two_stage.py"):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        continue
    t2 = io.open(p, encoding="utf-8", errors="replace").read()
    print("\n=== %s 采样/后端 ===" % rel)
    for ln in t2.splitlines():
        if re.search(r"temperature|top_p|max_tokens|8081|llama|gguf|judge", ln):
            print("   " + ln.strip()[:112])
