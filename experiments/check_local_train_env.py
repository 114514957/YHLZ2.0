# -*- coding: utf-8 -*-
"""本地能不能跑 4-bit QLoRA：查 bitsandbytes / 显存 / 依赖。"""
from __future__ import annotations

import importlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for mod in ("torch", "transformers", "peft", "bitsandbytes", "datasets", "accelerate"):
    try:
        m = importlib.import_module(mod)
        print("%-14s %s" % (mod, getattr(m, "__version__", "?")))
    except Exception as ex:  # noqa: BLE001
        print("%-14s ❌ %s" % (mod, type(ex).__name__))

out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.free",
                      "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
print("\n显存：%s" % out)

try:
    import bitsandbytes as bnb
    import torch
    print("bnb 可用：cuda_setup %s" % ("OK" if torch.cuda.is_available() else "无 CUDA"))
except Exception as ex:  # noqa: BLE001
    print("bnb 不可用：%s" % ex)
