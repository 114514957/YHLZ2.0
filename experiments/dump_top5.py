# -*- coding: utf-8 -*-
"""打印前 5 大块的完整原文（供压缩重写）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
import importlib  # noqa: E402

TP = importlib.import_module("backend.target_prompts")
NAMES = ["CRUTCH_BAN_CLAUSE", "SOCIAL_POSTURE_CLAUSE", "SELF_MODEL_CLAUSE",
         "VOICE_ANCHOR", "ANTI_HALLUCINATION"]
out = []
for name in NAMES:
    v = getattr(TP, name, "")
    print("=" * 70)
    print("### %s（%d 字）" % (name, len(v)))
    print(v)
    out.append("### %s\n%s" % (name, v))
io.open(os.path.join(ROOT, "cache", "top5_blocks.txt"), "w",
        encoding="utf-8").write("\n\n".join(out))
print("\n（已存 cache/top5_blocks.txt）")
