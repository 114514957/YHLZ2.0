# -*- coding: utf-8 -*-
"""打印 st02/st03/st05 的 style 规则具体值。"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\tools")
import persona_bank as PB  # noqa: E402

for bid in ("st01", "st02", "st03", "st05", "st08"):
    e = PB.by_id(bid)
    s = e.get("style") or {}
    print("%-4s 问：%s" % (bid, (e.get("q") or "")[:40]))
    if not s:
        print("   无 style 规则")
    for k, v in s.items():
        print("   %-22s %s" % (k, v))
    print()
