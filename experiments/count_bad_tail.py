# -*- coding: utf-8 -*-
"""统计：有多少训练样本的最后一条不是 assistant（这类样本在教模型说用户的话）。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")

for fn in ("sft_persona_v9t11_train.jsonl", "sft_persona_v9t11_val.jsonl"):
    rows = [json.loads(x) for x in io.open(os.path.join(PKG, fn), encoding="utf-8") if x.strip()]
    last = Counter((r["messages"][-1].get("role") if r.get("messages") else "空") for r in rows)
    print("%-34s %d 条｜最后一条角色分布：%s" % (fn, len(rows), dict(last)))
    bad = [r for r in rows if r.get("messages") and r["messages"][-1].get("role") != "assistant"]
    if bad:
        src = Counter(str(r.get("source", "")).split(":")[0] for r in bad)
        print("   非 assistant 结尾 %d 条｜来源：%s" % (len(bad), dict(src)))
        for r in bad[:3]:
            print("   样例 [%s]：%s" % (r.get("source", "")[:40],
                                      [m.get("role") for m in r["messages"]]))
    print()
