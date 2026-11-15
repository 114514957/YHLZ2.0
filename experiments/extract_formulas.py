# -*- coding: utf-8 -*-
"""从 trainer 源码里把公式抠出来（不凭印象）：损失、调度、裁剪、重采样。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
T = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v11", "finetune_train.py")
lines = io.open(T, encoding="utf-8", errors="replace").read().splitlines()

PATTERNS = {
    "调度器": r"lr_scheduler|get_cosine|scheduler_type|TrainingArguments",
    "损失/标签": r"labels|ignore_index|-100|CrossEntropy|DataCollator",
    "裁剪": r"max_grad_norm|clip",
    "重采样": r"rng\.choices|weights=|total=",
    "LoRA": r"LoraConfig|lora_alpha|lora_r",
    "量化": r"load_in_4bit|nf4|double_quant|compute_dtype",
}
for label, pat in PATTERNS.items():
    print("=" * 70)
    print("### " + label)
    for i, ln in enumerate(lines):
        if re.search(pat, ln):
            print("  %4d %s" % (i + 1, ln.strip()[:112]))
