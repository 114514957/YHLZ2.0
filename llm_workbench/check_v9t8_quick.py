# -*- coding: utf-8 -*-
"""v9t8 包装前体检（简版，直接指定文件）。"""
from __future__ import annotations

import io
import json
import os
import re
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")

RULES = [
    ("否认自己是 AI", re.compile(r"(我不是 ?AI|不(是|算) ?AI|我不是(人工)?智能)")),
    ("自称助手/客服", re.compile(r"(我是(你的)?(专属)?(AI ?)?助手|作为(一个)?助手|客服)")),
    ("认错创造者", re.compile(r"(我(的)?创造者是(?!老爹)|我妈|我主人)")),
    ("自我贬低", re.compile(r"(我只是(一)?个?(程序|工具|模型)|我就是个大?语言模型|没有(灵魂|意识|自我))")),
    ("客服腔", re.compile(r"(为您|需要我|有什么可以帮|随时待命|很高兴为您)")),
    ("平台标记残留", re.compile(r"(\[\[at:|\[\[reply:|\[\[dev:|<tool_call>)")),
]

rows = []
for fn in sorted(os.listdir(PACK)):
    if fn.endswith((".jsonl",)) and ("train" in fn or "val" in fn):
        with io.open(os.path.join(PACK, fn), encoding="utf-8") as f:
            rows += [json.loads(x) for x in f if x.strip()]

print("v9t8 %d 条" % len(rows))
for label, rx in RULES:
    hits = [r for r in rows
            if rx.search([m["content"] for m in r["messages"] if m["role"] == "assistant"][-1])]
    print("  %-14s %s %d" % (label, "✅" if not hits else "✗", len(hits)))
    for h in hits[:2]:
        print("      %s" % [m["content"] for m in h["messages"] if m["role"] == "assistant"][-1][:54])

lens = [len([m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]) for r in rows]
print("  长度中位 %d | ≤20 字 %.1f%%" % (statistics.median(lens),
                                      100 * sum(1 for x in lens if x <= 20) / len(lens)))
op = Counter([m["content"] for m in r["messages"] if m["role"] == "assistant"][-1][:2]
             for r in rows)
top = op.most_common(1)[0]
print("  最强开头 %r %.2f%%" % (top[0], 100 * top[1] / len(rows)))
print("  哈希唯一 %d / %d" % (len({r.get("content_hash") for r in rows}), len(rows)))
