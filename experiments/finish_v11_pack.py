# -*- coding: utf-8 -*-
"""补齐 v11 包（训练脚本/预检/MANIFEST/tar）。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")
OUT = os.path.join(YH, "dist", "retrain_pkg_gemma_v11")
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v11.tar.gz")

for f in ("finetune_train.py", "preflight_mlp.py"):
    shutil.copy2(os.path.join(SRC, f), os.path.join(OUT, f))


def lines(p):
    return sum(1 for x in io.open(p, encoding="utf-8") if x.strip())


tr = lines(os.path.join(OUT, "sft_persona_v11_train.jsonl"))
va = lines(os.path.join(OUT, "sft_persona_v11_val.jsonl"))

# Σw 复核
eff = 0.0
by = {}
for fn in ("sft_persona_v11_train.jsonl", "sft_persona_v11_val.jsonl"):
    for x in io.open(os.path.join(OUT, fn), encoding="utf-8"):
        if not x.strip():
            continue
        r = json.loads(x)
        w = float(r.get("weight", 1.0) or 1.0)
        eff += w
        s = str(r.get("source", "")).split(":")[0]
        by[s] = by.get(s, 0.0) + w

man = {
    "version": "v11",
    "purpose": "把以前没用上的素材全部纳入（子目录 4 万块 + 口述故事 556 段）",
    "data": {"train": tr, "val": va, "total": tr + va, "sigma_w": round(eff)},
    "top_sources": sorted(by.items(), key=lambda kv: -kv[1])[:12],
    "weights": {"dad_story": 3.5, "lccc": 0.15, "persona_gen": 0.35,
                "expand_story": 1.0, "greet": 4.0, "scold": 2.0, "longsent": 1.5,
                "other": 0.25},
    "training_plan": {"steps": (-(-tr // 8)), "lr": 1.5e-4, "epochs": 1,
                      "minutes": "90-120", "base": "gemma-4-e4b-it"},
    "known_risk": "口述故事占 25.3% Σw，可能训成讲故事的人；短答退化就把 3.5 降到 2.0-2.5",
    "acceptance": "56 题 ≥49 + 群聊 ≥27 + 闸门过 + st01 短答不退化",
}
with io.open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(man, f, ensure_ascii=False, indent=1)

if os.path.exists(TAR):
    os.remove(TAR)
subprocess.run(["tar", "-czf", TAR, "retrain_pkg_gemma_v11"],
               cwd=os.path.join(YH, "dist"), check=True)
sha = hashlib.sha256(open(TAR, "rb").read()).hexdigest()
print("train %d｜val %d｜Σw %.0f" % (tr, va, eff))
print("tar %d 字节｜sha256 %s…" % (os.path.getsize(TAR), sha[:16]))
print("步数 %d｜预计 %.0f 分钟" % (-(-tr // 8), (-(-tr // 8)) * 3.2 / 60))
