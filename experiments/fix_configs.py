# -*- coding: utf-8 -*-
"""重建三个配置（plan 命名冲突把 0.7/0.3 覆盖了，顺手改成不冲突的 id）。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CFG = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\experiments\configs"
base = json.load(io.open(os.path.join(CFG, "base_private.json"), encoding="utf-8"))

LORA = "models/gguf-lora/yuanheng-%s-lora.gguf"

CASES = [
    ("blend73", "F1 = v9t7:0.7+v9t8:0.3（冠军配置·复原）", [("v9t7", 0.7), ("v9t8", 0.3)]),
    ("f1-82", "F1 = v9t7:0.8+v9t8:0.2", [("v9t7", 0.8), ("v9t8", 0.2)]),
    ("f1-64", "F1 = v9t7:0.6+v9t8:0.4", [("v9t7", 0.6), ("v9t8", 0.4)]),
]

for cid, name, parts in CASES:
    cfg = json.loads(json.dumps(base))
    cfg["id"] = cid
    cfg["name"] = name
    cfg["model"]["lora"] = [{"path": LORA % v, "scale": s} for v, s in parts]
    p = os.path.join(CFG, "%s.json" % cid)
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    print("写出 %s" % os.path.basename(p))

for stale in ("base-f11.json", "base-f12.json"):
    p = os.path.join(CFG, stale)
    if os.path.exists(p):
        os.remove(p)
        print("删除 %s（plan 生成时覆盖过配置）" % stale)
