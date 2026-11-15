# -*- coding: utf-8 -*-
"""正式训练 v13（5641 条 / 1 epoch / 706 步），后台跑并落日志。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)
sftp = cli.open_sftp()


def sh(cmd: str, timeout: int = 150) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


# 正式配置：路径改成云端 + 输出目录
import json  # noqa: E402

cfg = json.load(open(os.path.join(ROOT, "dist", "material_v13", "config",
                                  "finetune.gemma4.v13.json"), encoding="utf-8"))
cfg.update({
    "base_model": "/root/autodl-tmp/models/gemma-4-e4b-it",
    "train_file": "/root/yh/material_v13/sft_persona_v13_train.jsonl",
    "val_file": "/root/yh/material_v13/sft_persona_v13_val.jsonl",
    "output_dir": "/root/autodl-tmp/models/lora/yuanheng-v13",
})
local_cfg = os.path.join(ROOT, "dist", "_v13_pack", "train_v13_full.json")
open(local_cfg, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
sftp.put(local_cfg, "/root/yh/material_v13/train_v13_full.json")
print("配置已传；关键项：epochs=%s lr=%s attn=%s bs=%sx%s"
      % (cfg["epochs"], cfg["lr"], cfg["attn_implementation"],
         cfg["batch_size"], cfg["grad_accum"]))

print(sh("cd /root/yh/material_v13 && rm -f v13.log && "
         "setsid nohup /root/miniconda3/bin/python -u train_v13.py "
         "--config train_v13_full.json > v13.log 2>&1 < /dev/null & "
         "sleep 3; echo started; nvidia-smi --query-gpu=memory.used --format=csv,noheader"))

# 等前 12 步，确认 gradcheck 与 loss 走势就返回（不阻塞到最后）
DEADLINE = time.time() + 600
while time.time() < DEADLINE:
    log = sh("tail -c 6000 /root/yh/material_v13/v13.log 2>/dev/null")
    if "[gradcheck]" in log and "'loss'" in log:
        break
    if "RuntimeError" in log or "Traceback" in log:
        break
    time.sleep(20)

log = sh("tail -c 8000 /root/yh/material_v13/v13.log 2>/dev/null")
print("=" * 74)
keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
        "trainable params", "丢弃", "重采样", "RuntimeError", "Traceback",
        "'loss'", "总步数")
for line in log.splitlines():
    s = line.strip()
    if any(k in s for k in keys):
        print(s[:150])
sftp.close()
cli.close()
