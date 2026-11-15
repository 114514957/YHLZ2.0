# -*- coding: utf-8 -*-
"""把 layer 0 的所有张量列出来，看清 Gemma4 的层内结构（为什么 42 层有 122 个 down_proj）。"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = (r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gemma4-hf"
     r"\gemma-4-e4b-it\model.safetensors")

with open(P, "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    hdr = json.loads(f.read(n).decode("utf-8"))
t = {k: v for k, v in hdr.items() if k != "__metadata__"}

l0 = {k: v for k, v in t.items() if k.startswith("model.language_model.layers.0.")}
print("layer0 张量 %d 个：" % len(l0))
for k in sorted(l0):
    print("   %-64s %s" % (k.replace("model.language_model.layers.0.", ""), l0[k]["shape"]))

print("\n每个 layer 的 down_proj 数量分布：")
c = Counter()
for k in t:
    if "down_proj" in k and ".layers." in k:
        c[k.split(".layers.")[1].split(".")[0]] += 1
print("   ", dict(list(c.items())[:12]), "… 种类：", set(c.values()))

print("\n前缀分布（去掉层号的模板）：")
import re
tpl = Counter(re.sub(r"\.layers\.\d+\.", ".layers.N.", k) for k in t if ".layers." in k)
for k, v in tpl.most_common(20):
    print("   %-72s %d" % (k, v))
