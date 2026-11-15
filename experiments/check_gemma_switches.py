# -*- coding: utf-8 -*-
"""查训练器有没有开 Gemma/QLoRA 那几个"必须开"的开关。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
T = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v11", "finetune_train.py")
L = io.open(T, encoding="utf-8", errors="replace").read().splitlines()

CHECKS = {
    "enable_input_require_grads（梯度检查点+LoRA 必须开）": r"enable_input_require_grads",
    "gradient_checkpointing_enable": r"gradient_checkpointing_enable",
    "use_cache=False": r"use_cache\s*=\s*False",
    "attn_implementation（eager/sdpa/fa2）": r"attn_implementation",
    "torch_dtype / dtype": r"torch_dtype|dtype\s*=",
    "padding_side（训练须 left? 其实 right）": r"padding_side",
    "skip_kbit_prepare": r"skip_kbit_prepare|prepare_model_for_kbit_training",
    "prepare_inputs_for_generation": r"prepare_inputs_for_generation",
    "resume/adapter 加载": r"PeftModel|from_pretrained\(",
}
for label, pat in CHECKS.items():
    hits = [(i + 1, l.strip()) for i, l in enumerate(L) if re.search(pat, l)]
    print("=" * 70)
    print("%s → %d 处" % (label, len(hits)))
    for ln, txt in hits[:6]:
        print("   %4d %s" % (ln, txt[:110]))
