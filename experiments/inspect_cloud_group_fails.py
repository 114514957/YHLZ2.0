# -*- coding: utf-8 -*-
"""看云端基线里群聊失败项的原文（改提示词前必看）。"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import group_bank as GB  # noqa: E402

D = json.load(open(os.path.join(ROOT, "cache", "eval_云端基线.json"), encoding="utf-8"))
fails = [r for r in D["detail"]["group"] if not r["ok"]]
print("群聊失败 %d 道\n" % len(fails))
for r in fails:
    e = GB.by_id(r["id"]) or {}
    print("=" * 72)
    print("%s｜%s" % (r["id"], str(e.get("scene") or "")[:40]))
    for m in (e.get("messages") or [])[-2:]:
        print("   问：%s" % str(m.get("content") or "")[:70])
    print("   判定：%s" % str(r.get("why"))[:90])
    print("   实答：%s" % str(r.get("ans") or "").replace("\n", " ")[:170])
