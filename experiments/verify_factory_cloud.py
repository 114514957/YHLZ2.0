# -*- coding: utf-8 -*-
"""端到端：走**生产工厂**（QQ/工作台用的那条路）问一句，确认走云端并记账。"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.llm_router import health  # noqa: E402
from backend.target_orchestrator import build_openai_compatible_llm_turn  # noqa: E402

USAGE = os.path.join(ROOT, "cache", "llm_usage.jsonl")


def lines() -> int:
    if not os.path.exists(USAGE):
        return 0
    return sum(1 for _ in io.open(USAGE, encoding="utf-8", errors="replace"))


print("端点：%s" % json.dumps(health(), ensure_ascii=False))
before = lines()
print("调用前记账行数：%d" % before)

turn = build_openai_compatible_llm_turn(temperature=0.7, max_tokens=120)
print("工厂已建（未传 base_url/model/api_key，应由 endpoint 解析）")

t0 = time.time()
try:
    out = asyncio.run(turn([{"role": "system", "content": "你是元亨，短句、第一人称、不助理腔。"},
                            {"role": "user", "content": "在吗"}], []))
    dt = time.time() - t0
    print("✅ 调用成功｜%.2f 秒" % dt)
    if isinstance(out, dict):
        print("   返回字段：%s" % sorted(out)[:10])
        print("   文本：%s" % str(out.get("content") or out.get("text") or out)[:120])
    else:
        print("   返回：%s" % str(out)[:160])
except Exception as ex:  # noqa: BLE001
    print("❌ 失败：%s: %s" % (type(ex).__name__, str(ex)[:300]))

after = lines()
print("\n记账行数：%d → %d（新增 %d）" % (before, after, after - before))
if after > before:
    last = io.open(USAGE, encoding="utf-8").read().strip().splitlines()[-1]
    print("最后一行：%s" % last[:220])
from backend.llm_usage import summary  # noqa: E402
print("汇总：%s" % json.dumps(summary(), ensure_ascii=False))
