# -*- coding: utf-8 -*-
"""把快照时机从改前改到改后（改后才是可回滚的状态）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "prompt_overrides.py")
t = io.open(P, encoding="utf-8").read()

start = t.find("def set_block(")
end = t.find("def reset_all(")
assert start > 0 and end > start, "定位失败"
seg = t[start:end]

seg2 = seg.replace('    _snapshot_before(key, "set")\n', "")
marker = "    _save(d)\n"
addition = (
    "    _save(d)\n"
    "    # 2026-11-15（台账 1256）：改后存快照——这才是「可以回去的状态」。\n"
    "    # 改前存的话，回滚等于回滚成「还没改」，对排查没有意义。\n"
    '    _snapshot_before(key, "after-set")\n'
)
if marker in seg2:
    seg2 = seg2.replace(marker, addition, 1)
else:
    print("⚠ 没找到 _save(d) 调用")
t = t[:start] + seg2 + t[end:]
io.open(P, "w", encoding="utf-8").write(t)
print("已改：after-set 在文件里 =", "after-set" in t)
