# -*- coding: utf-8 -*-
"""补齐：各版基座、qwen 期配置、以及 eval56 记录里的分数。"""
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

print("=" * 72)
print("① v3/v4/v6 用的基座")
print("=" * 72)
for z in sorted(glob.glob(os.path.join(ROOT, "dist", "finetune_bundle_v*.zip"))):
    ver = re.search(r"v(\d+)\.zip", z).group(1)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if n.endswith("config/finetune.cloud.json"):
                c = json.loads(zf.read(n).decode("utf-8-sig"))
                print("   v%-3s base=%s" % (ver, str(c.get("base_model"))[-60:]))

print()
print("=" * 72)
print("② qwen 期配置（v9t2..v9t6）")
print("=" * 72)
for p in sorted(glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_v9t*", "config", "*.json"))):
    c = json.load(open(p, encoding="utf-8-sig"))
    print("   %-42s lr=%-8s ep=%-4s bs=%s ga=%s seq=%s full=%s"
          % (os.path.basename(os.path.dirname(os.path.dirname(p))),
             c.get("lr"), c.get("epochs"), c.get("batch_size"),
             c.get("grad_accum"), c.get("max_seq_len"), c.get("full_finetune")))

print()
print("=" * 72)
print("③ eval56 记录里的分数")
print("=" * 72)
for p in sorted(glob.glob(os.path.join(ROOT, "cache", "eval56*.json"))):
    try:
        d = json.load(open(p, encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        continue
    # 兼容多种结构
    ok = tot = None
    if isinstance(d, dict):
        for k in ("ok", "passed", "score", "pass"):
            if isinstance(d.get(k), int):
                ok = d[k]
                break
        for k in ("total", "n", "count"):
            if isinstance(d.get(k), int):
                tot = d[k]
                break
        if ok is None and isinstance(d.get("results"), list):
            rs = d["results"]
            ok = sum(1 for r in rs if r.get("ok"))
            tot = len(rs)
    print("   %-34s %s/%s" % (os.path.basename(p), ok, tot))

print()
print("=" * 72)
print("④ DPO 配置（dist/dpo_style_v1/v2）")
print("=" * 72)
for p in sorted(glob.glob(os.path.join(ROOT, "dist", "dpo_style_v*", "*.json")) +
                glob.glob(os.path.join(ROOT, "dist", "dpo_style_v*", "**", "*.json"),
                          recursive=True)):
    try:
        c = json.load(open(p, encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        continue
    keys = {k: c.get(k) for k in ("beta", "learning_rate", "num_train_epochs",
                                  "per_device_train_batch_size", "gradient_accumulation_steps",
                                  "loss_type") if k in c}
    if keys:
        print("   %-40s %s" % (os.path.relpath(p, ROOT)[-40:], keys))
