# -*- coding: utf-8 -*-
"""看 QQ 会话文件的结构：有几轮、字段是什么、时间戳怎么存。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

for p in sorted(glob.glob(os.path.join(YH, "cache", "sessions", "qq_*.json"))):
    size = os.path.getsize(p)
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        print("%-34s %8d B  解析失败 %s" % (os.path.basename(p), size, ex))
        continue
    kind = type(d).__name__
    n = len(d) if hasattr(d, "__len__") else 0
    print("\n%-34s %8d B  %s  %d 项" % (os.path.basename(p), size, kind, n))
    if isinstance(d, dict):
        print("   键：%s" % list(d.keys())[:8])
        for k in ("messages", "history", "turns", "log"):
            if k in d and isinstance(d[k], list):
                msgs = d[k]
                print("   %s：%d 条；样例 %s"
                      % (k, len(msgs), json.dumps(msgs[-1], ensure_ascii=False)[:180]
                         if msgs else ""))
                break
    elif isinstance(d, list) and d:
        print("   样例：%s" % json.dumps(d[-1], ensure_ascii=False)[:200])
