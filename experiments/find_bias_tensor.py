# -*- coding: utf-8 -*-
"""找出唯一的 .bias 张量是谁，并核对总参数量（不加载模型，只读 safetensors 头）。"""
from __future__ import annotations

import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it", "model.safetensors")

with open(P, "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    h = json.loads(f.read(n))
ks = [k for k in h if k != "__metadata__"]
bias = [k for k in ks if k.endswith(".bias")]
print("张量总数：%d" % len(ks))
print("带 .bias 的：%s" % (bias or "无"))
print("per_layer 相关：%s" % [k for k in ks if "per_layer" in k][:4])
print("lm_head：%s" % ([k for k in ks if "lm_head" in k] or "无（tied）"))
print("embed_tokens：%s" % [k for k in ks if "embed_tokens" in k])

total = 0
for k in ks:
    o = h[k].get("data_offsets") or [0, 0]
    total += int(o[1]) - int(o[0])
print("权重总字节：%.2f GB（bf16 即约 %.2fB 参数）" % (total / 1e9, total / 2 / 1e9))
