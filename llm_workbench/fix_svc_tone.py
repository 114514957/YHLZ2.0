# -*- coding: utf-8 -*-
"""修 v9t8 里的真问题：客服腔样本；并把 [[dev:]] 从"残留"规则里排除。"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")
BAD = re.compile(r"随时待命|很高兴为您|为您服务|有什么可以帮")

total = fixed = 0
for fn in sorted(os.listdir(PACK)):
    if not fn.endswith(".jsonl"):
        continue
    p = os.path.join(PACK, fn)
    rows = [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
    out, n = [], 0
    for r in rows:
        total += 1
        a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
        if BAD.search(a):
            # 只剪掉客服腔那半句，保留前面；剪完为空则整条丢
            parts = re.split(r"[，。！]", a)
            keep = [x for x in parts if x and not BAD.search(x)]
            new = "，".join(keep).strip("，。 ")
            if not new:
                n += 1
                fixed += 1
                continue
            for m in r["messages"]:
                if m["role"] == "assistant":
                    m["content"] = new
            n += 1
            fixed += 1
        out.append(r)
    if n:
        with io.open(p, "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("%s：修 %d 条，剩 %d" % (fn, n, len(out)))

print("\n共扫 %d 条，修 %d 条" % (total, fixed))
