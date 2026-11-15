# -*- coding: utf-8 -*-
"""验 v7b 的 adapter：target_modules 是什么、有没有 MLP 张量、多大。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
D = os.path.join(YH, "models", "lora", "yuanheng-v7b-sft")

cfg = json.load(io.open(os.path.join(D, "adapter_config.json"), encoding="utf-8"))
print("v7b adapter_config：")
for k in ("r", "lora_alpha", "target_modules", "base_model_name_or_path", "peft_type"):
    print("  %-24s %s" % (k, cfg.get(k)))

from safetensors import safe_open  # noqa: E402

p = os.path.join(D, "adapter_model.safetensors")
print("\n文件：%s（%d 字节 / %.1f MB）" % (os.path.basename(p), os.path.getsize(p),
                                     os.path.getsize(p) / 1048576))
with safe_open(p, "pt") as f:
    keys = list(f.keys())
    print("张量 %d 个" % len(keys))
    mods = Counter()
    for k in keys:
        for m in ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"):
            if ".%s." % m in k:
                mods[m] += 1
    print("按模块统计：%s" % dict(mods))
    print("\n样例（MLP 的）：")
    n = 0
    for k in keys:
        if any(x in k for x in ("gate_proj", "up_proj", "down_proj")):
            print("  %-80s %s" % (k, tuple(f.get_slice(k).get_shape())))
            n += 1
            if n >= 4:
                break

# 对照：v9t8（attention-only）
D2 = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t8")
p2 = os.path.join(D2, "adapter_model.safetensors")
with safe_open(p2, "pt") as f:
    keys2 = list(f.keys())
    mods2 = Counter()
    for k in keys2:
        for m in ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"):
            if ".%s." % m in k:
                mods2[m] += 1
print("\n对照 v9t8：%d 张量 / %d 字节 / 模块 %s"
      % (len(keys2), os.path.getsize(p2), dict(mods2)))
