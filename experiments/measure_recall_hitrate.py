# -*- coding: utf-8 -*-
"""实测：拿真实 QQ 对话跑 contextual_recall，看命中率与命中质量。

这是"记忆到底在不在用"的直接证据（access_count 是只读设计，不算证据）。
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.target_memory import TargetMemoryService  # noqa: E402

svc = TargetMemoryService(db_path=os.path.join(ROOT, "cache", "memstore", "memstore.db"))

# 收集真实用户发言
turns: list[str] = []
for p in sorted(glob.glob(os.path.join(ROOT, "cache", "sessions", "qq_*.json"))):
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    msgs = d if isinstance(d, list) else (d.get("messages") or d.get("history") or [])
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            t = str(m.get("content") or "").strip()
            if len(t) >= 6:
                turns.append(t)

# 再加 qq_daily 里的真实提问
for p in glob.glob(os.path.join(ROOT, "cache", "qq_daily", "*.jsonl")):
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if r.get("role") == "user":
            t = str(r.get("text") or "").strip()
            if len(t) >= 6:
                turns.append(t)

print("真实用户发言样本：%d 条（≥6 字）" % len(turns))
if not turns:
    sys.exit("没有可用样本")

hits_total = 0
shown = 0
for t in turns:
    try:
        got = svc.contextual_recall(t, limit=3)
    except Exception as ex:  # noqa: BLE001
        print("  ❌ recall 抛异常：%s: %s" % (type(ex).__name__, ex))
        break
    if got:
        hits_total += 1
        if shown < 8:
            shown += 1
            print("\n问：%s" % t[:70])
            for h in got[:2]:
                print("   命中[%s|imp=%s] %s"
                      % (h.get("type"), h.get("importance"),
                         str(h.get("summary"))[:100]))

print("\n=== 结论 ===")
print("命中 %d / %d = %.1f%%" % (hits_total, len(turns), 100 * hits_total / len(turns)))
