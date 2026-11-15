# -*- coding: utf-8 -*-
"""查绘图库是否可用。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
for m in ("matplotlib", "numpy", "pandas"):
    try:
        mod = __import__(m)
        print("%-12s %s" % (m, getattr(mod, "__version__", "?")))
    except Exception as ex:  # noqa: BLE001
        print("%-12s 缺 %s" % (m, type(ex).__name__))
