# -*- coding: utf-8 -*-
"""盘训练素材：按来源统计条数 / Σ权重 / 长度，看这批数据到底由什么构成。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

TARGETS = sorted(glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_*", "sft_persona_*_train.jsonl")))
if not TARGETS:
    sys.exit("没找到训练集")

for p in TARGETS:
    print("=" * 78)
    print(os.path.relpath(p, ROOT))
    rows = []
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        print("  （空）")
        continue
    keys = sorted({k for r in rows[:200] for k in r})
    print("  条数 %d｜字段 %s" % (len(rows), keys))

    by = defaultdict(lambda: {"n": 0, "w": 0.0, "chars": 0})
    for r in rows:
        src = str(r.get("source") or "（无 source）")
        # 归一到"来源族"：取第一个分隔符之前
        fam = re.split(r"[/:|]", src)[0].strip() or "（空）"
        w = float(r.get("weight") or 1.0)
        msgs = r.get("messages") or []
        txt = "".join(str(m.get("content") or "") for m in msgs if isinstance(m, dict))
        d = by[fam]
        d["n"] += 1
        d["w"] += w
        d["chars"] += len(txt)

    tot_n = sum(v["n"] for v in by.values())
    tot_w = sum(v["w"] for v in by.values())
    print("  %-24s %6s %8s %10s %10s" % ("来源族", "条数", "占比", "Σ权重", "占权重"))
    for fam, v in sorted(by.items(), key=lambda x: -x[1]["w"])[:18]:
        print("  %-24s %6d %7.1f%% %10.1f %9.1f%%  (均 %d 字)"
              % (fam[:24], v["n"], 100 * v["n"] / tot_n, v["w"],
                 100 * v["w"] / tot_w if tot_w else 0,
                 v["chars"] / max(1, v["n"])))
    print("  %-24s %6d %7.1f%% %10.1f %9.1f%%"
          % ("合计", tot_n, 100.0, tot_w, 100.0))
    print()
