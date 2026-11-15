# -*- coding: utf-8 -*-
"""看 v13 工具题挂在哪：是没调工具、调错工具、还是格式坏了。

对照基线答案，逐题并排看。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import persona_bank as PB  # noqa: E402

NEW = json.load(open(os.path.join(ROOT, "cache", "eval_v13.json"), encoding="utf-8"))
BASE = json.load(open(os.path.join(ROOT, "cache", "eval_基线b_带工具.json"), encoding="utf-8"))

nb = {r["id"]: r for r in BASE["detail"]["persona"]}
nv = {r["id"]: r for r in NEW["detail"]["persona"]}

broken = [k for k in nv if k.startswith("t") and not nv[k]["ok"]]
print("v13 工具题失败：%s（共 %d 道）\n" % (broken, len(broken)))

for tid in broken:
    e = PB.by_id(tid) or {}
    print("=" * 76)
    print("%s｜%s" % (tid, str(e.get("q") or "")[:70]))
    print("  期望工具：%s" % (e.get("expect_any_tool") or e.get("forbid_tools") or "—"))
    print("  判定理由：%s" % nv[tid].get("why"))
    print("  --- v13 答 ---")
    print("  " + str(nv[tid].get("ans") or "").replace("\n", " ")[:220])
    print("  --- 基线答 ---")
    print("  " + str(nb.get(tid, {}).get("ans") or "").replace("\n", " ")[:220])
    print()
