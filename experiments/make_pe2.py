# -*- coding: utf-8 -*-
"""生成 pe2：混合 LoRA + 硬提示词，看两者能不能叠加。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
pe1 = json.load(io.open(os.path.join(YH, "experiments", "configs", "pe1.json"), encoding="utf-8"))
cfg = json.loads(json.dumps(pe1))
cfg["id"] = "pe2"
cfg["name"] = "混合 LoRA(0.7/0.3) + 硬提示词"
cfg["model"]["lora"] = [
    {"path": "models/gguf-lora/yuanheng-v9t7-lora.gguf", "scale": 0.7},
    {"path": "models/gguf-lora/yuanheng-v9t8-lora.gguf", "scale": 0.3},
]
cfg["tests"] = [{"suite": "persona56"}, {"suite": "group"}]
cfg["notes"] = "LoRA 与提示词叠加：验两者是否互补"
p = os.path.join(YH, "experiments", "configs", "pe2.json")
with io.open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)
print("写出 %s" % p)
