# -*- coding: utf-8 -*-
"""建全量微调包 v9f1：数据沿用 v9t10（可比），只改训练方式与超参。"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")
DAT = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")     # 完整素材集（8850 条）
OUT = os.path.join(YH, "dist", "retrain_pkg_gemma_v9f1")

os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
for f in ("finetune_train.py", "preflight_mlp.py"):
    shutil.copy2(os.path.join(SRC, f), os.path.join(OUT, f))
for f in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    shutil.copy2(os.path.join(DAT, f),
                 os.path.join(OUT, f.replace("v10u", "v9f1")))

cfg = {
    "_说明": ("v9f1：**全量微调**。数据用 v10u 的完整素材集（8850 条，含护栏提权 288 + 真实荤话 7），"
              "换训练方式：全参 bf16 + 8bit AdamW，lr 1e-5（比 LoRA 低 20 倍），1 epoch，"
              "冻结视觉/音频塔与词嵌入（台账 0760 的边界）。"),
    "base_model": "/root/autodl-tmp/models/gemma-4-e4b-it",
    "train_file": "/root/yh/retrain_pkg_gemma_v9f1/sft_persona_v9f1_train.jsonl",
    "val_file": "/root/yh/retrain_pkg_gemma_v9f1/sft_persona_v9f1_val.jsonl",
    "output_dir": "/root/autodl-tmp/models/full/yuanheng-v9f1-gemma",
    "max_seq_len": 1536,
    "epochs": 1.0,
    "batch_size": 8,
    "grad_accum": 1,
    "eval_batch_size": 4,
    "lr": 1e-05,
    "weight_decay": 0.0,
    "warmup_ratio": 0.03,
    "lr_scheduler_type": "cosine",
    "optim": "paged_adamw_8bit",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ".*language_model\\..*\\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)",
    "full_finetune": True,
    "freeze_external": True,
    "load_in_4bit": False,
    "bnb_4bit_quant_type": "nf4",
    "use_double_quant": True,
    "bnb_compute_dtype": "bf16",
    "gradient_checkpointing": True,
    "mask_prompt": True,
    "logging_steps": 20,
    "save_steps": 300,
    "save_total_limit": 1,
    "save_only_model": True,
    "report_to": "none",
    "seed": 20261109,
}
with io.open(os.path.join(OUT, "config", "finetune.gemma4.v9f1full.json"), "w",
             encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)

n = sum(1 for x in io.open(os.path.join(OUT, "sft_persona_v9f1_train.jsonl"),
                           encoding="utf-8") if x.strip())
print("包建好：%s｜train %d 条" % (OUT, n))
print("步数 ceil(%d/8) = %d" % (n, -(-n // 8)))
