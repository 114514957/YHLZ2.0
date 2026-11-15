# -*- coding: utf-8 -*-
"""列出工作台当前页签与卡片（核对进度用）。"""
from __future__ import annotations

import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
t = io.open(ROOT + r"\assets\webui\index.html", encoding="utf-8").read()
print("页签:", re.findall(r'data-panel="([a-z]+)"', t)[:6])
cards = [c.strip() for c in re.findall(r"<h3>([^<]{1,26})", t)]
print("卡片 %d 个：" % len(cards))
for i, c in enumerate(cards, 1):
    print("  %2d. %s" % (i, c))
