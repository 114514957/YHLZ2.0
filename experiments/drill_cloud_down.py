# -*- coding: utf-8 -*-
"""断网演练：把端点指到死地址，确认**明确报错**而不是静默降级（老爹 1231：无本地兜底）。

同时验证：重试确实发生、失败也记账（ok=false）。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

USAGE = os.path.join(ROOT, "cache", "llm_usage.jsonl")


def lines() -> int:
    return sum(1 for _ in io.open(USAGE, encoding="utf-8", errors="replace")) \
        if os.path.exists(USAGE) else 0


os.environ["YHLZ_LLM_BASE_URL"] = "http://127.0.0.1:9/v1/chat/completions"
from backend import llm_endpoint as EP  # noqa: E402
EP.reload()
from backend import llm_router as R  # noqa: E402

print("端点已指向死地址：%s" % EP.endpoint()["base_url"])
before = lines()
import time  # noqa: E402
t0 = time.time()
try:
    R.chat([{"role": "user", "content": "在吗"}], retries=3, timeout=5)
    print("❌ 竟然成功了——说明没有真的打到死地址")
except R.LLMUnavailable as ex:
    print("✅ 明确报错（LLMUnavailable）：%s" % str(ex)[:120])
except Exception as ex:  # noqa: BLE001
    print("⚠ 抛了别的异常：%s: %s" % (type(ex).__name__, str(ex)[:120]))
dt = time.time() - t0
print("   耗时 %.1f 秒（含 3 次重试退避 0.8+1.6=2.4 秒）" % dt)

after = lines()
print("\n记账：%d → %d（新增 %d，应为 1 条 ok=false）" % (before, after, after - before))
if after > before:
    print("   " + io.open(USAGE, encoding="utf-8").read().strip().splitlines()[-1][:200])

os.environ.pop("YHLZ_LLM_BASE_URL", None)
EP.reload()
print("\n已还原端点：%s" % EP.endpoint()["base_url"])
