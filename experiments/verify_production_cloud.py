# -*- coding: utf-8 -*-
"""生产切换验收：确认 daemon 真的在走云端，并且一次真实对话被记账。"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8321"
USAGE = os.path.join(ROOT, "cache", "llm_usage.jsonl")


def lines() -> int:
    return sum(1 for _ in io.open(USAGE, encoding="utf-8", errors="replace")) \
        if os.path.exists(USAGE) else 0


print("=== ① daemon /health ===")
with OPENER.open(BASE + "/health", timeout=10) as r:
    print("   " + r.read().decode()[:220])

before = lines()
print("\n=== ② 发一句真实对话（走 daemon → 工厂 → 云端）===")
body = json.dumps({"text": "在吗", "channel": "console"}, ensure_ascii=False).encode()
req = urllib.request.Request(BASE + "/talk", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with OPENER.open(req, timeout=180) as r:
        raw = r.read().decode("utf-8", "replace")
    print("   HTTP ok｜%.1f 秒" % (time.time() - t0))
    print("   返回前 300 字：%s" % raw.replace("\n", " ")[:300])
except Exception as ex:  # noqa: BLE001
    print("   ❌ %s: %s" % (type(ex).__name__, str(ex)[:200]))

time.sleep(3)
after = lines()
print("\n=== ③ 记账 ===")
print("   行数 %d → %d（新增 %d）" % (before, after, after - before))
if after > before:
    for ln in io.open(USAGE, encoding="utf-8").read().strip().splitlines()[-max(1, after - before):]:
        print("   " + ln[:200])
else:
    print("   ⚠ 没有新增记账——说明这次没走工厂路径（可能走了流式，流式记账在 router）")

from backend.llm_usage import summary  # noqa: E402
print("\n=== ④ 汇总 ===\n   %s" % json.dumps(summary(), ensure_ascii=False))
