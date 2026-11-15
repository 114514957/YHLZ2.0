# -*- coding: utf-8 -*-
"""看 v10u（完整素材集版）和 v9_train_bundle 各有多少条。"""
from __future__ import annotations

import io
import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

for p in sorted(glob.glob(os.path.join(YH, "dist", "retrain_pkg_gemma_v10u", "*.jsonl"))):
    n = sum(1 for x in io.open(p, encoding="utf-8") if x.strip())
    print("%-56s %6d 条｜%.1f MB" % (os.path.basename(p), n,
                                    os.path.getsize(p) / 1048576))

print("\n--- dist/v9_train_bundle ---")
d = os.path.join(YH, "dist", "v9_train_bundle")
if os.path.isdir(d):
    for root, _dirs, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            print("  %-50s %.1f MB" % (os.path.relpath(p, d), os.path.getsize(p) / 1048576))
else:
    print("  不存在")
