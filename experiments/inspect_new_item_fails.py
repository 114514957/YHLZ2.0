# -*- coding: utf-8 -*-
"""看新题挂的原因：是模型答得不对，还是我出的题 keys 定错了。

只查新增题（p21+ / r11+ / t17+ / st09+）。
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import persona_bank as PB  # noqa: E402

D = json.load(open(os.path.join(ROOT, "cache", "eval_基线_152.json"), encoding="utf-8"))
NEW_PREFIX = re.compile(r"^(p(2[1-9]|[3-5]\d)|r(1[1-9]|[23]\d)|t(1[7-9]|[2-4]\d)|st(09|1\d|2\d))$")

fails = [r for r in D["detail"]["persona"] if not r["ok"] and NEW_PREFIX.match(str(r["id"]))]
print("新增题挂 %d 道\n" % len(fails))
for r in fails:
    e = PB.by_id(r["id"]) or {}
    print("=" * 74)
    print("%s｜%s" % (r["id"], str(e.get("q") or e.get("scene") or "")[:60]))
    print("  我的判据：keys=%s all_keys=%s 工具=%s max_len=%s"
          % (e.get("keys"), e.get("all_keys"), e.get("expect_any_tool"), e.get("max_len")))
    print("  判定：%s" % str(r.get("why"))[:100])
    print("  实际答：%s" % str(r.get("ans") or "").replace("\n", " ")[:160])
    print()
