# -*- coding: utf-8 -*-
"""群聊学习①：把「群情报」注入群回合上下文（台账 1261）。

老爹定调：**群聊才是学习的关键**。她要在群里"知道谁是谁、这群在聊什么"，
否则每次都是面对一堆匿名句子。

之前 `backend/qq_intel.py` 已经能算出情报卡（人数/活跃/话题/Top成员），但**没接线**。
这里接进 `target_entry` 的群分支，并只用 ≤300 字（不挤爆窗口）。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_entry.py")
t = io.open(P, encoding="utf-8").read()

anchor = '''            from backend.qq_main_memory import QqMainMemory
            social = QqMainMemory(self._qq_social_db).context(text, self.channel)
            if social:
                ctx_lines.append(social)'''
assert anchor in t, "群分支定位失败"

add = anchor + '''
            # 2026-11-16（台账 1261）：**群情报**——让她在群里知道谁是谁、这群在聊什么。
            # 数据来自 memstore 的 qq_social_*（人数/活跃/话题/Top成员/@她次数），≤300 字。
            try:
                import re as _re2

                from backend import qq_intel as _qi
                _m2 = _re2.search(r"g(\\d{5,15})", str(self.channel or ""))
                if _m2:
                    _card = _qi.card_text(_m2.group(1))
                    if _card:
                        ctx_lines.append(_card)
                        if os.environ.get("YHLZ_QQ_INTEL_DEBUG"):
                            print("[qq-intel] %s" % _card[:80], flush=True)
            except Exception as _ex:  # noqa: BLE001
                if os.environ.get("YHLZ_QQ_INTEL_DEBUG"):
                    print("[qq-intel] 跳过：%s" % type(_ex).__name__, flush=True)'''

t = t.replace(anchor, add, 1)
if "import os" not in t.split("\n\n")[0]:
    # target_entry 顶部未必 import os；函数内已多处局部 import，这里保险起见用局部
    t = t.replace('            try:\n                import re as _re2',
                  '            try:\n                import os\n                import re as _re2', 1)

io.open(P, "w", encoding="utf-8").write(t)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已接线群情报；编译:", "OK" if r.returncode == 0 else "失败")
if r.returncode != 0:
    print((r.stderr or "")[-400:])
