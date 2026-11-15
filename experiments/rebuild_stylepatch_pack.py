# -*- coding: utf-8 -*-
"""重建 stylepatch 包（v3 补丁）并写一个「省显存」的配置。"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")
PATCH = os.path.join(YH, "dist", "style_patch_v3", "patch.jsonl")
REPLAY = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
OUT = os.path.join(YH, "dist", "retrain_pkg_stylepatch")
rng = random.Random(20261111)

shutil.copy2(os.path.join(SRC, "finetune_train.py"), os.path.join(OUT, "finetune_train.py"))

patch = [json.loads(x) for x in io.open(PATCH, encoding="utf-8") if x.strip()]
replay = []
p = os.path.join(REPLAY, "sft_persona_v10u_train.jsonl")
if os.path.exists(p):
    replay = [{"messages": r["messages"], "source": "replay", "weight": 0.3}
              for r in (json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip())]
rng.shuffle(replay)
replay = replay[:250]

allr = patch + replay
rng.shuffle(allr)
n_val = max(16, len(allr) // 10)
with io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[:-n_val]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with io.open(os.path.join(OUT, "sft_persona_patch_val.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[-n_val:]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

cfg = {
    "_说明": "stylepatch v3：153 条补丁（含 24 个长句故事块）+ 250 replay@0.3；省显存配置。",
    "base_model": "models/gemma4-hf/gemma-4-e4b-it",
    "train_file": "retrain_pkg_stylepatch/sft_persona_patch_train.jsonl",
    "val_file": "retrain_pkg_stylepatch/sft_persona_patch_val.jsonl",
    "output_dir": "../models/lora/yuanheng-stylepatch3",
    "max_seq_len": 384,
    "epochs": 2.0,
    "batch_size": 1,
    "grad_accum": 8,
    "eval_batch_size": 1,
    "lr": 3e-05,
    "weight_decay": 0.0,
    "warmup_ratio": 0.05,
    "lr_scheduler_type": "cosine",
    "optim": "adamw_torch",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ".*language_model\\..*\\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)",
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "use_double_quant": True,
    "bnb_compute_dtype": "bf16",
    "gradient_checkpointing": False,
    "skip_kbit_prepare": True,
    "mask_prompt": True,
    "full_finetune": False,
    "logging_steps": 5,
    "save_steps": 100000,
    "save_total_limit": 1,
    "save_only_model": True,
    "report_to": "none",
    "seed": 20261111,
}
with io.open(os.path.join(OUT, "config", "finetune.stylepatch.json"), "w",
             encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)

tr = sum(1 for x in io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"),
                           encoding="utf-8") if x.strip())
print("train %d｜val %d｜步数 ceil(%d/8)*2 = %d"
      % (tr, n_val, tr, (-(-tr // 8)) * 2))
