# -*- coding: utf-8 -*-
"""让 POST /api/eval_run 也走 daemon（与 try_turn 同样的例外）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_daemon.py")
t = io.open(P, encoding="utf-8").read()

old = ('        if self.path.startswith("/api/") and not self.path.startswith(\n'
       '                "/api/try_turn"):')
new = ('        if self.path.startswith("/api/") and not self.path.startswith(\n'
       '                ("/api/try_turn", "/api/eval_run")):')
assert old in t, "定位失败"
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("POST 例外已扩到 /api/eval_run")
