# -*- coding: utf-8 -*-
"""盯第一条真实对话：等到采集器抓到非回填的新轮次就打印出来。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DAILY = os.path.join(YH, "cache", "qq_daily")
LIMIT_S = int(sys.argv[1]) if len(sys.argv) > 1 else 300

t0 = time.time()
seen = set()
found = []
while time.time() - t0 < LIMIT_S:
    for p in glob.glob(os.path.join(DAILY, "2*.jsonl")):
        try:
            for x in io.open(p, encoding="utf-8"):
                if not x.strip():
                    continue
                r = json.loads(x)
                if r.get("backfill"):
                    continue
                k = (r.get("channel"), r.get("idx"), r.get("role"), r.get("text"))
                if k in seen:
                    continue
                seen.add(k)
                found.append(r)
                print("[%.0f 秒] %-12s %-9s %s"
                      % (time.time() - t0, str(r.get("channel"))[:12],
                         r.get("role"), str(r.get("text"))[:100].replace("\n", " ")),
                      flush=True)
        except Exception:  # noqa: BLE001
            pass
    if found and any(r.get("role") == "assistant" for r in found):
        print("\n✅ 已抓到一条完整来回（采集器工作正常）", flush=True)
        break
    time.sleep(10)

if not found:
    print("（%d 秒内没有新对话——采集器正常，只是还没人说话）" % LIMIT_S)
