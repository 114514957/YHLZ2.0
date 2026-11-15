# -*- coding: utf-8 -*-
"""看现有题号与风格题的字段用法。"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import group_bank as GB  # noqa: E402
import persona_bank as PB  # noqa: E402

d = defaultdict(list)
for e in PB.PERSONA_BANK:
    d[str(e["id"])[0]].append(e["id"])
for k in sorted(d):
    print("%s → %s" % (k, d[k]))
print("group → %s" % [e["id"] for e in GB.GROUP_BANK])
print("\n风格题现有字段：")
for e in PB.PERSONA_BANK:
    if e.get("cat") == "风格":
        print("  %-4s keys=%-22s negative=%d max_len=%s no_tail=%s"
              % (e["id"], e.get("keys"), len(e.get("negative") or []),
                 e.get("max_len"), e.get("no_tail_question")))
