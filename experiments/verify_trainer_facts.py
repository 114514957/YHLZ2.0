# -*- coding: utf-8 -*-
"""核实白皮书要引用的实现细节（训练器 + 评测 + 导出）。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TRAINER = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v11", "finetune_train.py")

t = io.open(TRAINER, encoding="utf-8", errors="replace").read()
lines = t.splitlines()


def show(pat: str, label: str, limit: int = 3) -> None:
    print("\n-- %s --" % label)
    n = 0
    for i, ln in enumerate(lines):
        if re.search(pat, ln):
            print("   %4d  %s" % (i + 1, ln.strip()[:118]))
            n += 1
            if n >= limit:
                break


show(r"mask_prompt", "mask_prompt")
show(r"-100", "标签置 -100")
show(r"logging_steps|eval_strategy|save_strategy", "日志/评估/保存策略", 5)
show(r"LoraConfig|target_modules|modules_to_save|bias\s*=", "LoRA 配置", 6)
show(r"prepare_model_for|load_in_4bit|bnb_4bit", "量化与准备", 5)
show(r"max_grad_norm|gradient_accumulation|per_device_train_batch|num_train_epochs", "优化超参", 6)
show(r"rng.choices|weights=|_eff_avg", "权重重采样", 6)
show(r"warmup", "warmup", 4)

print("\n=== 评测脚本 ===")
for f in sorted(os.listdir(os.path.join(ROOT, "experiments"))):
    if re.search(r"(accept|eval56|judge|suite)", f) and f.endswith(".py"):
        print("   experiments/%s" % f)
for f in sorted(os.listdir(os.path.join(ROOT, "tools"))):
    if re.search(r"(eval|judge|accept|score)", f) and f.endswith(".py"):
        print("   tools/%s" % f)
