# -*- coding: utf-8 -*-
"""抽取 v3/v4/v6 配置、v8 adapter 参数、v6–v8 人格回归分数 → 时间线原材料。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "docs", "研究", "训练曲线", "timeline_raw.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

data = {"bundles": {}, "v8": {}, "eval_scores": {}}

print("=" * 72)
print("① 老 bundle 的配置")
print("=" * 72)
for z in sorted(glob.glob(os.path.join(ROOT, "dist", "finetune_bundle_v*.zip"))):
    ver = re.search(r"v(\d+)\.zip", z).group(1)
    try:
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.endswith(("config/finetune.json", "config/finetune.cloud.json")):
                    c = json.loads(zf.read(n).decode("utf-8-sig"))
                    key = "local" if n.endswith("finetune.json") else "cloud"
                    data["bundles"].setdefault("v" + ver, {})[key] = {
                        k: c.get(k) for k in
                        ("lr", "epochs", "batch_size", "grad_accum", "max_seq_len",
                         "lora_r", "lora_alpha", "optim", "base_model",
                         "full_finetune", "load_in_4bit", "train_file")
                    }
                    print("   v%s %-6s lr=%s ep=%s bs=%s ga=%s seq=%s r=%s α=%s %s"
                          % (ver, key, c.get("lr"), c.get("epochs"), c.get("batch_size"),
                             c.get("grad_accum"), c.get("max_seq_len"),
                             c.get("lora_r"), c.get("lora_alpha"),
                             "FULL" if c.get("full_finetune") else ""))
    except Exception as ex:  # noqa: BLE001
        print("   v%s 失败 %s" % (ver, ex))

print()
print("=" * 72)
print("② v8 adapter 参数")
print("=" * 72)
p = os.path.join(ROOT, "dist", "v8_adapter", "adapter_config.json")
if os.path.exists(p):
    c = json.load(open(p, encoding="utf-8-sig"))
    data["v8"] = {k: c.get(k) for k in ("r", "lora_alpha", "lora_dropout",
                                        "target_modules", "base_model_name_or_path",
                                        "task_type")}
    print("   r=%s α=%s dropout=%s base=%s"
          % (c.get("r"), c.get("lora_alpha"), c.get("lora_dropout"),
             str(c.get("base_model_name_or_path"))[-40:]))
    print("   target_modules=%s" % str(c.get("target_modules"))[:120])

print()
print("=" * 72)
print("③ 人格回归明细里的分数（v6/v7/v7b/v7c/v8）")
print("=" * 72)
for f in sorted(glob.glob(os.path.join(ROOT, "docs", "报告", "人格回归明细_*.md"))):
    t = io.open(f, encoding="utf-8", errors="replace").read()
    # 找 "通过 X/Y" 或 "X/Y" 形式的合计
    m = re.findall(r"(\d+)\s*/\s*(\d+)", t)
    best = None
    for a, b in m:
        if int(b) in (20, 25, 28, 30, 40, 50, 56) and int(a) <= int(b):
            if best is None or int(b) > best[1]:
                best = (int(a), int(b))
    name = os.path.basename(f)
    tag = re.search(r"_(v\d+b?c?)", name)
    key = tag.group(1) if tag else name
    if best:
        data["eval_scores"].setdefault(key, []).append(
            {"file": name, "score": best[0], "total": best[1]})
        print("   %-46s %s/%s" % (name[:46], best[0], best[1]))
    else:
        print("   %-46s （没解析到合计）" % name[:46])

json.dump(data, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n写入 %s" % OUT)
