# -*- coding: utf-8 -*-
"""建本地风格补丁训练包：patch 129 条 + replay 300 条（防忘），4-bit QLoRA。"""
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
PATCH = os.path.join(YH, "dist", "style_patch_v2", "patch.jsonl")
REPLAY_SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
OUT = os.path.join(YH, "dist", "retrain_pkg_stylepatch")
rng = random.Random(20261110)

os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
shutil.copy2(os.path.join(SRC, "finetune_train.py"), os.path.join(OUT, "finetune_train.py"))
shutil.copy2(os.path.join(SRC, "preflight_mlp.py"), os.path.join(OUT, "preflight_mlp.py"))

patch = [json.loads(x) for x in io.open(PATCH, encoding="utf-8") if x.strip()]
replay = []
for fn in ("sft_persona_v10u_train.jsonl",):
    p = os.path.join(REPLAY_SRC, fn)
    if os.path.exists(p):
        replay = [{"messages": r["messages"], "source": "replay", "weight": 0.3}
                  for r in (json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip())]
rng.shuffle(replay)
replay = replay[:300]

allr = patch + replay
rng.shuffle(allr)
n_val = max(20, len(allr) // 10)
with io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[:-n_val]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with io.open(os.path.join(OUT, "sft_persona_patch_val.jsonl"), "w", encoding="utf-8") as f:
    for r in allr[-n_val:]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

cfg = {
    "_说明": ("stylepatch：在 v9t10-dpo2 上做**小补丁 SFT**，只治 st02(长句)/st03(自称)/st05(叫老爹)。"
              "129 条原文+黄金（带权重）+ 300 条 replay（0.3）防遗忘；lr 2e-5、2 epoch、4-bit QLoRA，"
              "本机 8G 卡跑。"),
    "base_model": "models/gemma4-hf/gemma-4-e4b-it",
    "train_file": "sft_persona_patch_train.jsonl",
    "val_file": "sft_persona_patch_val.jsonl",
    "output_dir": "models/lora/yuanheng-stylepatch1",
    "max_seq_len": 512,
    "epochs": 2.0,
    "batch_size": 1,
    "grad_accum": 4,
    "eval_batch_size": 2,
    "lr": 2e-05,
    "weight_decay": 0.0,
    "warmup_ratio": 0.05,
    "lr_scheduler_type": "cosine",
    "optim": "paged_adamw_8bit",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ".*language_model\\..*\\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)",
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "use_double_quant": True,
    "bnb_compute_dtype": "bf16",
    "gradient_checkpointing": True,
    "mask_prompt": True,
    "full_finetune": False,
    "logging_steps": 5,
    "save_steps": 1000,
    "save_total_limit": 1,
    "save_only_model": True,
    "report_to": "none",
    "seed": 20261110,
}
with io.open(os.path.join(OUT, "config", "finetune.stylepatch.json"), "w",
             encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)

tr = sum(1 for x in io.open(os.path.join(OUT, "sft_persona_patch_train.jsonl"),
                            encoding="utf-8") if x.strip())
print("包建好：train %d｜val %d｜步数 ceil(%d/4)=%d"
      % (tr, n_val, tr, -(-tr // 4)))
