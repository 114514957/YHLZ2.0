# -*- coding: utf-8 -*-
"""看 NapCat 自己的日志：私信到底有没有到协议端。"""
from __future__ import annotations

import io
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SHELL = r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell"

for f in ("napcat.out.log", "napcat.err.log"):
    p = os.path.join(SHELL, f)
    if not os.path.exists(p):
        print("缺 %s" % f)
        continue
    t = io.open(p, encoding="utf-8", errors="replace").read()
    print("=== %s｜%.0f 分钟前写入｜%d 字节 ===" % (f, (time.time() - os.path.getmtime(p)) / 60, len(t)))
    lines = [x for x in t.splitlines() if x.strip()]
    print("\n".join(lines[-12:]))
    pri = [x for x in lines if "private" in x.lower() or "私聊" in x or "私信" in x]
    print("… 其中含 private/私聊 的行 %d 条" % len(pri))
    for x in pri[-5:]:
        print("   %s" % x[:160])
    print()

# 会话文件里私聊那份的最后一条
p = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\sessions\qq_qq_p2258374446.json"
if os.path.exists(p):
    import json
    d = json.load(io.open(p, encoding="utf-8"))
    h = d.get("history") or []
    print("私聊会话：%d 条｜最后 4 条：" % len(h))
    for m in h[-4:]:
        print("   %-9s %s" % (m.get("role"), (m.get("content") or "")[:80].replace("\n", " ")))
