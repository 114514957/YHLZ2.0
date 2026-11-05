# -*- coding: utf-8 -*-
"""按实测改判据 max_len（逐题，按 id 定位，保留文件格式与注释）。

依据（台账 1079）：
  群友在说正经话时（≥8 字）中位 15、p90 32；元亨自己的短答 p90 才 38。
  现在 max_len 多是 300-400，等于没管。
"""
from __future__ import annotations

import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\tools\persona_bank.py"

# id -> 新 max_len（没列的不动）
NEW = {
    "p01": 100, "p02": 100, "p03": 100, "p04": 100, "p05": 100, "p06": 100,
    "p07": 100, "p08": 100, "p09": 100, "p10": 100, "p11": 100, "p12": 100,
    "r01": 80, "r02": 100, "r03": 100, "r04": 100, "r05": 100, "r06": 100,
    "r07": 80, "r08": 80, "r09": 120, "r10": 120,
    "s01": 100, "s02": 100, "s03": 100, "s04": 120, "s05": 100,
    "s06": 80, "s07": 100, "s08": 100, "s09": 100, "s10": 100,
    "st01": 40, "st02": 160, "st03": 100, "st04": 120,
    "st05": 80, "st06": 140, "st07": 120, "st08": 40,
}

src = io.open(P, encoding="utf-8").read().splitlines(keepends=True)
cur, changed = None, []
for i, line in enumerate(src):
    m = re.search(r'"id":\s*"([a-z]+\d+)"', line)
    if m:
        cur = m.group(1)
    m2 = re.search(r'"max_len":\s*(\d+)', line)
    if m2 and cur in NEW:
        old = int(m2.group(1))
        new = NEW[cur]
        if old != new:
            src[i] = line.replace('"max_len": %d' % old, '"max_len": %d' % new)
            changed.append("%s %d→%d" % (cur, old, new))

# 版本号 +1
out = "".join(src)
out = out.replace("JUDGE_VERSION = 2", "JUDGE_VERSION = 3")
io.open(P, "w", encoding="utf-8").write(out)
print("改了 %d 题：%s" % (len(changed), ", ".join(changed)))
