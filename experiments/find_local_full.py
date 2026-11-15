# -*- coding: utf-8 -*-
"""找老爹拉到本地的全量产物（15.88GB 的 model.safetensors）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TARGET = 15882477500
ROOTS = [os.path.join(YH, "docs", "训练产物"),
         os.path.join(YH, "models"),
         os.path.join(YH, "dist"),
         os.path.join(YH, "cache", "_inbox")]

hits = []
for root in ROOTS:
    if not os.path.isdir(root):
        continue
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > 10 << 30 or (f == "model.safetensors" and sz > 1 << 30):
                hits.append((p, sz))

if hits:
    for p, sz in hits:
        print("%-80s %.2f GB %s" % (p, sz / 1e9, "✅ 与云端一致" if sz == TARGET else ""))
else:
    print("这几个目录里没有大文件；列出 docs/训练产物 的内容：")
    d = os.path.join(YH, "docs", "训练产物")
    if os.path.isdir(d):
        for dirpath, _dirs, files in os.walk(d):
            for f in files[:40]:
                p = os.path.join(dirpath, f)
                print("   %-70s %.1f MB" % (os.path.relpath(p, d),
                                            os.path.getsize(p) / 1048576))
