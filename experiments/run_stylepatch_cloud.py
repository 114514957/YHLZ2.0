# -*- coding: utf-8 -*-
"""在 dpo2 上跑 stylepatch 补丁（80 步）：写云端 config → 开训 → 确认起跑。"""
from __future__ import annotations

import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
DPO2 = "/root/autodl-tmp/models/lora/yuanheng-v9t10-dpo2"
PKG = "/root/yh/retrain_pkg_stylepatch"
OUT = "/root/autodl-tmp/models/lora/yuanheng-stylepatch4"
LOG = "/root/autodl-tmp/logs/train_stylepatch4.log"

CFG = {
    "_说明": "stylepatch4：在 v9t10-dpo2 上续训 153 条补丁（故事单轮长句24+黄金长句18+解释长句74+被凶自称33+问候4），"
             "治 st02 长句 / st03 自称 / st05 叫老爹。80 步，不改动其他能力。",
    "base_model": BASE,
    "train_file": PKG + "/sft_persona_patch_train.jsonl",
    "val_file": PKG + "/sft_persona_patch_val.jsonl",
    "output_dir": OUT,
    "max_seq_len": 640,
    "epochs": 2.0,
    "batch_size": 1,
    "grad_accum": 8,
    "eval_batch_size": 4,
    "lr": 3e-05,
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
    "bnb_compute_dtype": "fp32",
    "gradient_checkpointing": True,
    "skip_kbit_prepare": False,
    "mask_prompt": True,
    "full_finetune": False,
    "logging_steps": 5,
    "save_steps": 1000,
    "save_total_limit": 1,
    "save_only_model": True,
    "report_to": "none",
    "seed": 20261112,
}

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)


def q(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


payload = json.dumps(CFG, ensure_ascii=False, indent=1)
_i, o, _e = c.exec_command("cat > %s/config/finetune.stylepatch4.cloud.json" % PKG, timeout=60)
o.channel.sendall(payload.encode())
o.channel.shutdown_write()
o.channel.recv_exit_status()
print("config 写入：%s" % q("wc -c %s/config/finetune.stylepatch4.cloud.json" % PKG))

print("\n启动")
q("mkdir -p /root/autodl-tmp/logs && cd %s && "
  "TOKENIZERS_PARALLELISM=false setsid nohup /root/miniconda3/bin/python -u finetune_train.py "
  "--config config/finetune.stylepatch4.cloud.json --base %s --resume-from %s "
  "> %s 2>&1 < /dev/null & echo LAUNCHED" % (PKG, BASE, DPO2, LOG), t=120)

time.sleep(150)
print(q("pgrep -cf '[f]inetune_train.py' || echo 0"))
print(q("tr -d '\\r' < %s | grep -aE 'trainable|编码后保留|权重重采样|总步数|已保存' | tail -6" % LOG))
print(q("tr -d '\\r' < %s | tail -c 200" % LOG))
c.close()
