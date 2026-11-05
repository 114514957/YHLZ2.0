# -*- coding: utf-8 -*-
"""定长度基线：群友真正在"说话"（≥8 字）时的分布 vs 元亨通过题时的长度。"""
from __future__ import annotations

import glob
import io
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_qq_peers  # noqa: F401,E402  （import 时会重跑并打印，忽略）

# 群友语料（上一步已落盘）
data = json.load(io.open(os.path.join(YH, "docs", "研究", "群友语料候选_20261104.json"),
                         encoding="utf-8"))
# 从上一步的统计里拿不到全部原文，重扫一遍导出更准
import mine_qq  # noqa: F401,E402

rows = []
for p in sorted(glob.glob(os.path.join(YH, "cache", "qq_export", "*.jsonl"))):
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        t = (r.get("text") or "").strip()
        if not t:
            continue
        is_bot = (str(r.get("sender_id")) == "3655185302"
                  or str(r.get("message_id", "")).startswith("bot:"))
        rows.append((is_bot, t))

human = [t for b, t in rows if not b]
bot = [t for b, t in rows if b]


def pct(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


for label, arr, floor in (("群友 全部", human, 1),
                          ("群友 ≥8字（在说正经话）", human, 8),
                          ("群友 ≥15字", human, 15),
                          ("元亨 全部", bot, 1),
                          ("元亨 ≤40字（短答）", bot, 1)):
    xs = [len(t) for t in arr if len(t) >= floor]
    if not xs:
        continue
    if label == "元亨 ≤40字（短答）":
        xs = [x for x in xs if x <= 40]
    print("%-22s n=%4d | 中位 %3d | p75 %3d | p90 %3d"
          % (label, len(xs), statistics.median(xs), pct(xs, 0.75), pct(xs, 0.90)))
