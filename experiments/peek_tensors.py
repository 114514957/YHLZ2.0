# -*- coding: utf-8 -*-
"""读 safetensors 头，确认 down_proj / o_proj 的确切模块路径和中间维（不加载权重）。"""
from __future__ import annotations

import json
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = (r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gemma4-hf"
     r"\gemma-4-e4b-it\model.safetensors")

with open(P, "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    hdr = json.loads(f.read(n).decode("utf-8"))

tensors = {k: v for k, v in hdr.items() if k != "__metadata__"}
print("张量 %d 个" % len(tensors))

pat = ("down_proj", "o_proj", "gate_proj", "up_proj")
for p in pat:
    hits = [k for k in tensors if p in k]
    print("\n%s：%d 个" % (p, len(hits)))
    for k in hits[:3]:
        print("   %-70s %s" % (k, tensors[k]["shape"]))

lay = sorted({k.split(".layers.")[1].split(".")[0]
              for k in tensors if ".layers." in k})
print("\n层号：%s …（共 %d 层）" % (lay[:5], len(lay)))
