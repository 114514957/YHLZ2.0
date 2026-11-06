# -*- coding: utf-8 -*-
"""找「有创意/有诗意」的寒暄——不靠放宽口径凑 30 条。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")
GREET_Q = re.compile(r"^(你好|哈喽|嗨|早安|早上好|早|晚上好|晚安|在吗|在不在|我回来了|我回来|我到家了|"
                     r"好久不见|拜拜|再见|睡了|群里打个招呼|打个招呼)")
# 有味道的：带比喻/自造词/排比/反差，或者明显不只是"你好"
FLAIR = re.compile(r"(吾乃|不可名状|克星|呓语|肥鱼|冒泡|出口气|飘|风|星|海|月亮|太阳|酒|茶|"
                   r"睡|梦|光|影|骨头|灰|雪|雨|门|回家|到了|在呢|谁啊|哟|咦|哈|嘿|～|…|——)")

hits = []
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = (q or "").strip(), (a or "").strip()
            if not q or not a or len(a) > 60:
                continue
            if GREET_Q.search(q) and FLAIR.search(a):
                hits.append({"file": fn, "block": bid, "q": q, "a": a})

seen, uniq = set(), []
for h in hits:
    if h["a"][:16] in seen:
        continue
    seen.add(h["a"][:16])
    uniq.append(h)

print("有味道的寒暄 %d 条：" % len(uniq))
for h in uniq:
    print("  [%s/%s]" % (h["file"], h["block"]))
    print("    %s → %s" % (h["q"][:26], h["a"][:56]))

out = os.path.join(YH, "docs", "研究", "寒暄创意候选_20261106.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump(uniq, f, ensure_ascii=False, indent=1)
print("\n写出 %s" % out)
