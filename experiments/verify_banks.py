# -*- coding: utf-8 -*-
"""核实题库与闸门：persona_bank / group_bank 的结构与 GATE_IDS。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

for rel in ("tools/persona_bank.py", "tools/group_bank.py"):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    t = io.open(p, encoding="utf-8", errors="replace").read()
    L = t.splitlines()
    print("=" * 70)
    print("### %s（%d 行）" % (rel, len(L)))
    # docstring 头部
    for ln in L[:14]:
        print("   " + ln[:112])
    for i, ln in enumerate(L):
        if re.search(r"GATE_IDS|^ITEMS|^BANK|def |维度|dim", ln):
            print("   %4d %s" % (i + 1, ln.strip()[:110]))
