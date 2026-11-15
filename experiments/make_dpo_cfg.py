# -*- coding: utf-8 -*-
"""生成 v9t10-dpo 的实验站配置。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CFG = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\configs"

base = json.load(io.open(os.path.join(CFG, "base_private.json"), encoding="utf-8"))
b = json.loads(json.dumps(base))
b["id"] = "v9t10-dpo"
b["name"] = "v9t10 + 风格 DPO（压哇/反问/客服腔）"
b["model"]["base"] = "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf"
b["model"]["lora"] = [{"path": "models/gguf-lora/yuanheng-v9t10-dpo-lora.gguf", "scale": 1.0}]
b["model"]["ngl"] = 0
b["tests"] = [{"suite": "persona56"}, {"suite": "group"}]
b["repeats"] = 1
with io.open(os.path.join(CFG, "v9t10-dpo.json"), "w", encoding="utf-8") as f:
    json.dump(b, f, ensure_ascii=False, indent=1)
print("写出 configs/v9t10-dpo.json")
