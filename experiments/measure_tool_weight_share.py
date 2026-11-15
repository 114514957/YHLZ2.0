# -*- coding: utf-8 -*-
"""量：工具类样本在 v9t10 / v13 里的**权重占比**（不是条数），看被挤掉多少。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def buckets(path: str) -> dict:
    tot_w = 0.0
    agg = defaultdict(lambda: {"n": 0, "w": 0.0})
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        ms = [m for m in (r.get("messages") or []) if isinstance(m, dict)]
        w = float(r.get("weight") or 1.0)
        tot_w += w
        has_tc = any(m.get("tool_calls") for m in ms)
        has_tool_role = any(m.get("role") == "tool" for m in ms)
        src = str(r.get("source") or "")
        if has_tc or has_tool_role:
            k = "工具调用样本"
        elif src.startswith("v11_dad_story"):
            k = "口述故事"
        elif "discipline" in src or "harden" in src:
            k = "纪律/加固"
        else:
            k = "其余"
        agg[k]["n"] += 1
        agg[k]["w"] += w
    out = {k: {"n": v["n"], "w": round(v["w"], 1),
               "pct": round(100 * v["w"] / tot_w, 1)} for k, v in agg.items()}
    out["_total_w"] = round(tot_w, 1)
    return out


for name, rel in (("v9t10", r"dist\retrain_pkg_gemma_v9t10\sft_persona_v9t10_train.jsonl"),
                  ("v13", r"dist\material_v13\sft_persona_v13_train.jsonl")):
    b = buckets(os.path.join(ROOT, rel.replace("\\", os.sep)))
    print("=== %s（Σ权重 %s）===" % (name, b.pop("_total_w")))
    for k, v in sorted(b.items(), key=lambda x: -x[1]["w"]):
        print("   %-12s %5d 条｜Σw %8.1f｜占权重 %5.1f%%" % (k, v["n"], v["w"], v["pct"]))
    print()
