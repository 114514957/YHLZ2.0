# -*- coding: utf-8 -*-
"""重做 v9t9 的数据：要「素材齐全 + 权重合理」，现在那份两条都不满足。

现用（v9t6 数据）的问题：
  · 缺 4 个来源共 384 条：identity_ai 15、internal_refusal 5、material_full 287、qq_short 77
  · 多 687 条 memory_qstyle（688 条以「记得。」开头，全是内部工程决策）——v9t7 专门删的
  · 权重：memory_qstyle Σw 206.1 = **5.81%**，单来源破 5% 红线（1113）

v9t8 数据的问题：
  · 齐全，但 material_full 287 条 @0.8 = Σw 229.6 = **6.29%**，也破 5% 红线（正是 v9t8 掉工具的原因）

所以这一版 = **v9t8 的数据（齐全）+ 权重修正（material_full 0.8→0.4）+ MLP**。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")
DST = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")

MLP_RE = r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
DOWNWEIGHT = {"material_full": 0.4}     # 0.8 → 0.4（1113 的规矩：单来源 Σw ≤5%）

os.makedirs(os.path.join(DST, "config"), exist_ok=True)
rows = []
for fn in ("sft_persona_v9t8_train.jsonl", "sft_persona_v9t8_val.jsonl"):
    with io.open(os.path.join(SRC, fn), encoding="utf-8") as f:
        part = [json.loads(x) for x in f if x.strip()]
    for r in part:
        src = str(r.get("source", "")).split(":")[0]
        if src in DOWNWEIGHT:
            r["weight"] = DOWNWEIGHT[src]
    rows += part
    out = os.path.join(DST, fn.replace("v9t8", "v9t10"))
    with io.open(out, "w", encoding="utf-8") as f:
        for r in part:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("  ✓ %-34s %d 条" % (os.path.basename(out), len(part)))

shutil.copy2(os.path.join(SRC, "finetune_train.py"), os.path.join(DST, "finetune_train.py"))

cfg = json.load(io.open(os.path.join(SRC, "config", "finetune.gemma4.v9t8lora.json"),
                        encoding="utf-8"))
cfg["target_modules"] = MLP_RE
cfg["train_file"] = "/root/yh/retrain_pkg_gemma_v9t10/sft_persona_v9t10_train.jsonl"
cfg["val_file"] = "/root/yh/retrain_pkg_gemma_v9t10/sft_persona_v9t10_val.jsonl"
cfg["output_dir"] = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10"
cfg["_说明"] = ("gemma v9t10：v9t8 的数据（齐全：含 identity_ai/internal_refusal/material_full/qq_short）"
                " + 权重修正（material_full 0.8→0.4，Σw 229.6→114.8）+ target_modules 加 MLP。"
                "相对 v9t8 变了两处：MLP（实验变量）、material_full 权重（按 1113 的规矩修）。")
p = os.path.join(DST, "config", "finetune.gemma4.v9t10lora.json")
with io.open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

# Σw 复核
eff = 0.0
by = defaultdict(lambda: [0, 0.0])
for r in rows:
    w = float(r.get("weight", 1.0) or 1.0)
    s = str(r.get("source", "")).split(":")[0]
    eff += w
    by[s][0] += 1
    by[s][1] += w
print("\nΣw 复核（红线：单来源 ≤5%%）：合计 %.0f" % eff)
bad = 0
for s, (c, w) in sorted(by.items(), key=lambda x: -x[1][1])[:8]:
    pct = 100 * w / eff
    flag = "⚠️超5%" if pct > 5 and s != "personality" and s != "scene" and s != "memory" else ""
    print("   %-18s %5d 条｜Σw %6.1f｜%5.2f%% %s" % (s, c, w, pct, flag))
print("\n（personality/scene/memory 是主体来源，本来就大，不适用 5% 红线；红线管新增来源）")
print("material_full：Σw %.1f = %.2f%%（原来 6.29%%）" % (by["material_full"][1],
                                                    100 * by["material_full"][1] / eff))
print("\n包 → %s（%d 条）" % (DST, len(rows)))
