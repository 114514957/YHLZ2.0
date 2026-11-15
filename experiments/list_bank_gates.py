# -*- coding: utf-8 -*-
"""列出两套题库的题数与闸门题。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\tools")

import group_bank as GB  # noqa: E402
import persona_bank as PB  # noqa: E402

for name, mod in (("persona_bank", PB), ("group_bank", GB)):
    items = None
    for attr in ("ITEMS", "BANK", "CASES", "SUITE"):
        if hasattr(mod, attr):
            items = getattr(mod, attr)
            print("%s.%s：%d 题" % (name, attr, len(items)))
            break
    if items is None:
        print("%s：没找到题目列表属性" % name)
        continue
    gates = [e.get("id") for e in items if (e.get("gate") or mod.is_gate(e))]
    print("   闸门题：%s" % gates)
    dims = {}
    for e in items:
        d = e.get("dim") or e.get("维度") or e.get("kind") or "?"
        dims[d] = dims.get(d, 0) + 1
    print("   维度分布：%s" % dims)
