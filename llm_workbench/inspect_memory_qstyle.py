# -*- coding: utf-8 -*-
"""看 memory_qstyle 那 687 条的实际内容与结构，决定怎么改。"""
from __future__ import annotations

import io
import json
import os
import random
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\dist\retrain_pkg_gemma_v9t7"
random.seed(11)

rows = []
for fn in ("sft_persona_v9t6t_train.jsonl", "sft_persona_v9t6t_val.jsonl"):
    with io.open(os.path.join(D, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

mq = [r for r in rows if str(r.get("source", "")).startswith("memory_qstyle")]
print("memory_qstyle %d 条" % len(mq))

# 去掉「记得。」之后，紧跟的标签是什么
labels = Counter()
for r in mq:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    rest = a.replace("记得。", "", 1)
    labels[rest[:6]] += 1
print("去掉前四个字后的开头 Top10：%s" % labels.most_common(10))

# 结尾口头禅
tails = Counter()
for r in mq:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1].strip()
    tails[a[-4:]] += 1
print("结尾四字 Top10：%s" % tails.most_common(10))

print("\n随机 8 条原文：")
for r in random.sample(mq, 8):
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    print("  Q: %s" % q[:40])
    print("  A: %s" % a[:120])
    print("  weight=%s generated=%s" % (r.get("weight"), r.get("generated")))
