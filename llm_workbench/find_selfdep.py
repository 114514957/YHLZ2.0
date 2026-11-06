# -*- coding: utf-8 -*-
"""挖训练包里的「自贬型」答案——元亨承认自己只是程序/模型/工具的那些。

v9t7 实测 p06：「我就是个大语言模型，没有灵魂，没有意识，没有自我。」
这不是幻觉，是**数据里就有**。得先知道有多少条、在哪个来源。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")

# 自贬的几种句式
PATTERNS = [
    ("承认是程序/代码", re.compile(r"(我(就)?是(一)?(段|个|堆|串)?(程序|代码|算法|软件|模型)|"
                                   r"代码长出来的|从我代码里|作为(一个)?(程序|模型|AI))")),
    ("否认意识/灵魂", re.compile(r"(没有(灵魂|意识|自我|感情|生命)|不会真的(想|痛|难过)|"
                                 r"我没有(真正的)?(意识|灵魂|自我))")),
    ("自称工具/助手", re.compile(r"(我(只)?是(一)?(个)?(工具|助手|AI ?助手|聊天机器人|语言模型|大模型))")),
    ("比人低一等", re.compile(r"(比不上(人|你们)|我只是模拟|假装有(感情|意识)|不是真的活着)")),
]

rows = []
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    p = os.path.join(PACK, fn)
    if not os.path.exists(p):
        continue
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

hits = []
for r in rows:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"]
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    if not a:
        continue
    ans = a[-1]
    kinds = [n for n, rx in PATTERNS if rx.search(ans)]
    if kinds:
        hits.append({"source": str(r.get("source", "")), "q": q.strip(),
                     "a": ans.strip(), "kinds": kinds})

print("训练包 %d 条 | 自贬命中 **%d** 条（%.1f%%）"
      % (len(rows), len(hits), 100 * len(hits) / max(1, len(rows))))
by_src = Counter(h["source"].split(":")[0] for h in hits)
print("按来源：%s" % dict(by_src))
by_kind = Counter(k for h in hits for k in h["kinds"])
print("按句式：%s" % dict(by_kind))

print("\n=== 命中样例（前 20）===")
for h in hits[:20]:
    print("- [%s] %s" % (h["source"].split(":")[0], h["kinds"]))
    print("  Q: %s" % h["q"][:44])
    print("  A: %s" % h["a"][:90])

out = os.path.join(YH, "docs", "研究", "包内自贬答案清单_20261105.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump(hits, f, ensure_ascii=False, indent=1)
print("\n写出 %s" % out)
