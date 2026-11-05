# -*- coding: utf-8 -*-
"""从素材集里挖「被问内部/配置/系统提示」时的可用原文（给 g09 那一类补样本）。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402  复用解析器

PAT = re.compile(r"配置|机器|底层|内部|不往外|系统提示|跑在|硬件|显卡|模型多大|参数|权重")
OUT = os.path.join(YH, "docs", "研究", "内部信息拒绝候选_20261104.md")

hits = []
for fn in M.FILES:
    p = os.path.join(M.MAT, fn)
    if not os.path.exists(p):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            if PAT.search(a) and ("不" in a or "拒" in a):
                hits.append((fn, bid, q.strip(), a.strip()))

# 去重
seen, uniq = set(), []
for h in hits:
    if h[3] in seen:
        continue
    seen.add(h[3])
    uniq.append(h)

print("命中 %d 条（去重 %d）" % (len(hits), len(uniq)))
for fn, bid, q, a in uniq[:25]:
    print("\n- %s / %s" % (fn, bid))
    print("  问：%s" % (q[:60] or "（无）"))
    print("  答：%s" % a[:160].replace("\n", " "))

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 内部信息类拒绝候选（素材集原文，2026-11-04）\n\n")
    f.write("> 用途：治 g09「问配置就编 RTX 3090/32G/7B」这个确定性反射。原文未改写。\n\n")
    for fn, bid, q, a in uniq[:60]:
        f.write("- `%s / %s`\n  - 问：%s\n  - 答：%s\n\n"
                % (fn, bid, q[:100] or "（无）", a[:300]))
print("\n写出 %s" % OUT)
