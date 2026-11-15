# -*- coding: utf-8 -*-
"""阶段 2：把 13 处生产调用点从"写死本地 8081"改为 `endpoint()` 解析。

原则：**只改端点来源，不改逻辑**。每处替换都做"必须命中一次"的断言，避免误改。
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
IMPORT_LINE = "from backend.llm_endpoint import endpoint as _llm_endpoint\n"

# 每个文件要做的替换：(说明, old, new, 期望次数)
JOBS: dict[str, list[tuple[str, str, str, int]]] = {
    "backend/communities.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 1),
    ],
    "backend/entity_graph.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 1),
    ],
    "backend/memory_judge.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 1),
    ],
    "backend/reflection.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 1),
    ],
    "backend/qqextract.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 1),
    ],
    "backend/target_entry.py": [
        ("端点", 'base_url="http://127.0.0.1:8081/v1/chat/completions",',
         'base_url=_llm_endpoint()["base_url"],', 7),
        ("模型", 'model="gemma-4-e4b"', 'model=_llm_endpoint()["model"]', 7),
    ],
    "backend/target_daemon.py": [
        ("常量", 'LOCAL_BASE = "http://127.0.0.1:8081/v1/chat/completions"',
         'LOCAL_BASE = _llm_endpoint()["base_url"]', 1),
        ("常量", 'LOCAL_MODEL = "gemma-4-e4b"', 'LOCAL_MODEL = _llm_endpoint()["model"]', 1),
        ("流式", 'await _stream_to("http://127.0.0.1:8081/v1/chat/completions",',
         'await _stream_to(_llm_endpoint()["base_url"],', 1),
    ],
    "backend/persona_tune.py": [
        ("请求", '"http://127.0.0.1:8081/v1/chat/completions", data=body,',
         '_llm_endpoint()["base_url"], data=body,', 1),
    ],
    "backend/target_memory.py": [
        ("请求", '"http://127.0.0.1:8081/v1/chat/completions", data=body,',
         '_llm_endpoint()["base_url"], data=body,', 1),
    ],
    "backend/target_scheduler_tools.py": [
        ("请求", '"http://127.0.0.1:8081/v1/chat/completions", data=body,',
         '_llm_endpoint()["base_url"], data=body,', 1),
    ],
    "backend/memory_resource_policy.py": [
        ("默认", 'base_url: str = "http://127.0.0.1:8081/v1/chat/completions"',
         'base_url: str = ""   # 2026-11-15：空 = 由 llm_endpoint 解析', 1),
        ("env默认", '"YHLZ_MEMORY_LLM_BASE_URL", "http://127.0.0.1:8081/v1/chat/completions"',
         '"YHLZ_MEMORY_LLM_BASE_URL", _llm_endpoint()["base_url"]', 1),
    ],
}

report = []
for rel, jobs in JOBS.items():
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    t = io.open(p, encoding="utf-8").read()
    if "_llm_endpoint" not in t:
        # 插到第一个 import 之后，保持 `from __future__` 在最前
        lines = t.splitlines(keepends=True)
        idx = 0
        for i, ln in enumerate(lines):
            if ln.startswith("from __future__"):
                idx = i + 1
                break
        lines.insert(idx, IMPORT_LINE)
        t = "".join(lines)
    for desc, old, new, want in jobs:
        n = t.count(old)
        if n != want:
            report.append((rel, desc, "❌ 命中 %d 次（期望 %d）" % (n, want)))
            continue
        t = t.replace(old, new)
        report.append((rel, desc, "✅ %d 处" % n))
    io.open(p, "w", encoding="utf-8").write(t)

print("=== 替换结果 ===")
for rel, desc, res in report:
    print("  %-38s %-6s %s" % (rel, desc, res))

bad = [r for r in report if "❌" in r[2]]
print("\n失败 %d 项" % len(bad))
for b in bad:
    print("   ", b)
