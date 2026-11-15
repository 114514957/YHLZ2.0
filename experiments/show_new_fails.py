# -*- coding: utf-8 -*-
"""看 DPO 新挂的几道题是什么。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\tools")
import persona_bank as PB  # noqa: E402
import group_bank as GB  # noqa: E402

for bid in ("t02", "t07", "r10"):
    try:
        e = PB.by_id(bid)
    except Exception:  # noqa: BLE001
        print("%s 找不到" % bid)
        continue
    print("%-4s [%s] %s" % (bid, e.get("cat"), (e.get("q") or "")[:70]))
    print("     期望：keys=%s neg=%s max_len=%s"
          % (e.get("keys"), (e.get("negative") or [])[:3], e.get("max_len")))

print()
for bid in ("g21", "g24", "g25"):
    e = next((x for x in GB.GROUP_BANK if x["id"] == bid), None)
    if not e:
        continue
    msg = e["messages"][-1]["content"] if e.get("messages") else ""
    print("%-4s [%s] %s" % (bid, e.get("scene"), msg[:50]))
