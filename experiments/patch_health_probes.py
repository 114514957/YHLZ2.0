# -*- coding: utf-8 -*-
"""把两处"探活本地 llama"改成探活 router 端点（云端时不该去敲 8081）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

JOBS = {
    "backend/target_scheduler_tools.py": [
        (
            'with _url.urlopen("http://127.0.0.1:8081/health", timeout=2) as r:',
            'with _url.urlopen(_llm_endpoint()["base_url"].replace("/v1/chat/completions", "/health"), timeout=3) as r:',
        ),
        (
            'with _url.urlopen("http://127.0.0.1:8081/props", timeout=2) as r:',
            'with _url.urlopen(_llm_endpoint()["base_url"].replace("/v1/chat/completions", "/props"), timeout=3) as r:',
        ),
    ],
    "backend/console_server.py": [
        (
            '"http://127.0.0.1:8081/health", timeout=3).read())',
            '(_llm_endpoint()["base_url"].replace("/v1/chat/completions", "/health")), timeout=3).read())',
        ),
    ],
}

for rel, pairs in JOBS.items():
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    t = io.open(p, encoding="utf-8").read()
    if "_llm_endpoint" not in t:
        lines = t.splitlines(keepends=True)
        idx = 0
        for i, ln in enumerate(lines):
            if ln.startswith("from __future__"):
                idx = i + 1
                break
        lines.insert(idx, "from backend.llm_endpoint import endpoint as _llm_endpoint\n")
        t = "".join(lines)
    for old, new in pairs:
        n = t.count(old)
        print("%-36s %s → 命中 %d" % (rel, old[:44], n))
        t = t.replace(old, new)
    io.open(p, "w", encoding="utf-8").write(t)
print("完成")
