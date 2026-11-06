# -*- coding: utf-8 -*-
"""看两个 adapter 的结构：张量名、形状、alpha/r，决定怎么合并。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
A = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t7")
B = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t8")

from safetensors import safe_open  # noqa: E402

for tag, d in (("v9t7", A), ("v9t8", B)):
    cfg = json.load(io.open(os.path.join(d, "adapter_config.json"), encoding="utf-8"))
    print("%s: r=%s alpha=%s dropout=%s" % (tag, cfg.get("r"), cfg.get("lora_alpha"),
                                            cfg.get("lora_dropout")))
    print("   target: %s" % cfg.get("target_modules"))
    with safe_open(os.path.join(d, "adapter_model.safetensors"), "pt") as f:
        keys = list(f.keys())
        print("   张量 %d 个" % len(keys))
        for k in keys[:4]:
            print("     %-70s %s" % (k, tuple(f.get_slice(k).get_shape())))
        # 汇总 A/B 形状
        a_shape = f.get_slice(keys[0]).get_shape()
    print()

# 键是否一致
with safe_open(os.path.join(A, "adapter_model.safetensors"), "pt") as fa:
    ka = set(fa.keys())
with safe_open(os.path.join(B, "adapter_model.safetensors"), "pt") as fb:
    kb = set(fb.keys())
print("键一致：%s（只 v9t7 有 %d，只 v9t8 有 %d）"
      % (ka == kb, len(ka - kb), len(kb - ka)))
