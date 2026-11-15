# -*- coding: utf-8 -*-
"""看 st 系列（风格题）到底考什么，以及 dpo2 现在挂在哪几道。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\tools")
import persona_bank as PB  # noqa: E402

for e in PB.PERSONA_BANK:
    if str(e.get("id", "")).startswith("st"):
        print("%-4s [%s]" % (e["id"], e.get("cat")))
        print("   问：%s" % (e.get("q") or "")[:70])
        print("   keys=%s" % (e.get("keys") or []))
        print("   neg=%s｜max_len=%s｜no_tail_q=%s"
              % ((e.get("negative") or [])[:5], e.get("max_len"),
                 e.get("no_tail_question")))
        print()
