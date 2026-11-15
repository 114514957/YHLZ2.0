# -*- coding: utf-8 -*-
"""修 target_entry 里写死的空 api_key（导致 401）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
p = os.path.join(ROOT, "backend", "target_entry.py")
t = io.open(p, encoding="utf-8").read()
old = 'api_key="", model=_llm_endpoint()["model"]'
new = 'api_key=_llm_endpoint()["api_key"], model=_llm_endpoint()["model"]'
n = t.count(old)
t = t.replace(old, new)
io.open(p, "w", encoding="utf-8").write(t)
print("修了 %d 处：api_key 由 endpoint 提供（原先写死空串 → 401）" % n)
