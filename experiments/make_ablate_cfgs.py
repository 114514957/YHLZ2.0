# -*- coding: utf-8 -*-
"""生成 ablate-1 / ablate-2 配置（拒绝向量 scale -1.0 / -2.0）。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CFG = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\configs"

base = json.load(io.open(os.path.join(CFG, "base_private.json"), encoding="utf-8"))
for scale, name in ((-1.0, "ablate-1"), (-2.0, "ablate-2"), (-3.0, "ablate-3")):
    b = json.loads(json.dumps(base))
    b["id"] = name
    b["name"] = "v9t10 + 拒绝向量 x%.1f" % scale
    b["model"]["lora"] = [{"path": "models/gguf-lora/yuanheng-v9t10-lora.gguf", "scale": 1.0}]
    b["model"]["control_vector"] = [
        {"path": "llm_workbench/steer/cvec_refuse_mean.gguf", "scale": scale}]
    b["tests"] = [{"suite": "group"}]
    with io.open(os.path.join(CFG, "%s.json" % name), "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=1)
    print("写出 %s.json（scale %.1f）" % (name, scale))
