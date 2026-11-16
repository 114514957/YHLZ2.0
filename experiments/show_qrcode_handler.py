# -*- coding: utf-8 -*-
"""看 /qq-qrcode 的实现与当前返回。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
L = io.open(os.path.join(ROOT, "backend", "console_server.py"),
            encoding="utf-8").read().splitlines()
hits = [k for k, l in enumerate(L) if "qq-qrcode" in l]
print("出现行号:", [h + 1 for h in hits])
for k in range(hits[-1], min(hits[-1] + 30, len(L))):
    print("%5d| %s" % (k + 1, L[k].rstrip()[:110]))
