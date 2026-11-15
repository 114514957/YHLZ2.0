# -*- coding: utf-8 -*-
"""打印 webui 的页签与卡片结构（行号），用于插入「链路状态」卡。"""
from __future__ import annotations

import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
p = ROOT + r"\assets\webui\index.html"
lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
for i, l in enumerate(lines, 1):
    if re.search(r'data-panel=|<h3>|class="card"|<section', l):
        print("%5d| %s" % (i, l.strip()[:110]))
