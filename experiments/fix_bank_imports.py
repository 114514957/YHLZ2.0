# -*- coding: utf-8 -*-
"""给两个 bank 补 pathlib 导入（我新加的加载代码用到了 Path）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

for rel in ("tools/persona_bank.py", "tools/group_bank.py"):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    t = io.open(p, encoding="utf-8").read()
    if "from pathlib import Path" in t:
        print("%s 已有 Path 导入" % rel)
        continue
    # 在 from __future__ 之后插入
    t = t.replace("from __future__ import annotations",
                  "from __future__ import annotations\n\nfrom pathlib import Path", 1)
    io.open(p, "w", encoding="utf-8").write(t)
    print("%s 已插入 Path 导入" % rel)
