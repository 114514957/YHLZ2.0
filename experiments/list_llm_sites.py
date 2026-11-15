# -*- coding: utf-8 -*-
"""列出所有后台认知任务用的 LLM：是本地 dpo2 还是云端默认。"""
from __future__ import annotations

import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

FILES = ["communities", "entity_graph", "memory_judge", "reflection", "qqextract",
         "target_entry", "target_daemon", "target_orchestrator"]
for f in FILES:
    p = ROOT + r"\backend\%s.py" % f
    try:
        t = io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        continue
    hits = [m.start() for m in re.finditer(r"build_openai_compatible_llm_turn\(", t)]
    if not hits:
        continue
    print("=== %s.py（%d 处）===" % (f, len(hits)))
    for i in hits:
        seg = re.sub(r"\s+", " ", t[i:i + 300])
        seg = seg.split(")")[0]
        local = "8081" in seg or "LOCAL_BASE" in seg
        kind = "本地" if local else "云端默认(DeepSeek)"
        print("   %-16s %s" % (kind, seg[:130]))
    print()
