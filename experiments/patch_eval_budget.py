# -*- coding: utf-8 -*-
"""让评测器也遵守工具预算（否则测不到"少给工具"的影响）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "experiments", "eval56_28.py")
t = io.open(P, encoding="utf-8").read()

anchor = "    if tools:\n        body[\"tools\"] = tools"
if anchor not in t:
    anchor = '    if tools:\n        body["tools"] = tools'
assert anchor in t, "找不到 tools 组装处"

add = '''    if tools and (os.getenv("YHLZ_TOOL_BUDGET") or "").strip() in ("1", "true", "on"):
        # 2026-11-15（台账 1257）：评测也按预算收窄工具，才能测到"少给工具"的影响。
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from backend import tool_budget as _tb
            _n0 = len(tools)
            tools = _tb.select(tools, user, None)
            if len(tools) != _n0:
                print("   [budget] %d→%d（%s）" % (_n0, len(tools), _tb.level_of(user)))
        except Exception:  # noqa: BLE001
            pass
'''
t = t.replace(anchor, add + anchor, 1)
io.open(P, "w", encoding="utf-8").write(t)
import subprocess
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已改评测器；编译:", "OK" if r.returncode == 0 else "失败")
