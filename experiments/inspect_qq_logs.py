# -*- coding: utf-8 -*-
"""看 qqwatch/all.jsonl 与 qq_export 的结构，确认能不能按天取。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

p = os.path.join(YH, "cache", "qqwatch", "all.jsonl")
print("== all.jsonl ==  %d 字节" % os.path.getsize(p))
rows = []
for x in io.open(p, encoding="utf-8", errors="replace"):
    if x.strip():
        try:
            rows.append(json.loads(x))
        except Exception:  # noqa: BLE001
            pass
print("条数 %d" % len(rows))
if rows:
    print("字段：%s" % list(rows[0].keys()))
    for r in rows[-3:]:
        s = json.dumps(r, ensure_ascii=False)
        print("   %s" % s[:230])

ex = sorted(glob.glob(os.path.join(YH, "cache", "qq_export", "*.jsonl")))
print("\n== qq_export ==  %d 个文件，最新 %s" % (len(ex), os.path.basename(ex[-1])))
sample = [json.loads(x) for x in io.open(ex[-1], encoding="utf-8", errors="replace")
          if x.strip()]
print("条数 %d｜字段 %s" % (len(sample), list(sample[0].keys()) if sample else "?"))
for r in sample[:2]:
    print("   %s" % json.dumps(r, ensure_ascii=False)[:240])
