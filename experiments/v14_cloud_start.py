# -*- coding: utf-8 -*-
"""v14 上云：上传 → 冒烟（看 gradcheck）→ 通过则自动开正式训练。"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
RDIR = "/root/yh/material_v14"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=40)
sftp = cli.open_sftp()


def sh(cmd: str, timeout: int = 300) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


print("=== 环境 ===")
print(sh("nvidia-smi --query-gpu=name,memory.free --format=csv,noheader; df -h /root/autodl-tmp | tail -1"))

print("\n=== 上传 ===")
sh("mkdir -p %s" % RDIR)
UPS = [
    (os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_train.jsonl"), "train.jsonl"),
    (os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_val.jsonl"), "val.jsonl"),
    (os.path.join(ROOT, "dist", "material_v14", "smoke", "smoke60_train.jsonl"), "smoke60_train.jsonl"),
    (os.path.join(ROOT, "dist", "material_v14", "smoke", "smoke60.json"), "smoke60.json"),
    (os.path.join(ROOT, "dist", "material_v13", "train_v13.py"), "train_v13.py"),
]
cfg = json.load(open(os.path.join(ROOT, "dist", "material_v14", "config",
                                  "finetune.gemma4.v14.json"), encoding="utf-8"))
cfg.update({"base_model": "/root/autodl-tmp/models/gemma-4-e4b-it",
            "train_file": "%s/train.jsonl" % RDIR,
            "val_file": "%s/val.jsonl" % RDIR,
            "output_dir": "/root/autodl-tmp/models/lora/yuanheng-v14"})
local_cfg = os.path.join(ROOT, "dist", "material_v14", "smoke", "cfg_full.json")
open(local_cfg, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
UPS.append((local_cfg, "cfg.json"))

for local, name in UPS:
    sftp.put(local, "%s/%s" % (RDIR, name))
    print("   %-22s %.1f MB" % (name, os.path.getsize(local) / 1048576))

# 云端冒烟配置的路径也要对
print(sh("cd %s && sed -i 's#/root/yh/material_v14/#%s/#g' smoke60.json && "
         "grep -o '\"train_file\": \"[^\"]*\"' smoke60.json" % (RDIR, RDIR)))

print("\n=== 冒烟 ===")
print(sh("cd %s && rm -f smoke.log && setsid nohup /root/miniconda3/bin/python -u "
         "train_v13.py --config smoke60.json > smoke.log 2>&1 < /dev/null & sleep 2; echo started"
         % RDIR))

deadline = time.time() + 900
smoke_ok = False
while time.time() < deadline:
    log = sh("tail -c 4000 %s/smoke.log" % RDIR, 60)
    if "[gradcheck]" in log:
        m = re.search(r"非零梯度 (\d+) 个", log)
        nz = int(m.group(1)) if m else -1
        if "train_runtime" in log:
            print(log[-1200:])
            smoke_ok = nz > 0
            break
    if "Traceback" in log or "RuntimeError" in log:
        print("冒烟失败：\n" + log[-1500:])
        break
    time.sleep(20)

print("\n冒烟判定：%s" % ("✅ 通过" if smoke_ok else "❌ 未通过"))

if smoke_ok:
    print("\n=== 正式训练 ===")
    print(sh("cd %s && rm -f v14.log && setsid nohup /root/miniconda3/bin/python -u "
             "train_v13.py --config cfg.json > v14.log 2>&1 < /dev/null & sleep 2; echo started"
             % RDIR))
sftp.close()
cli.close()
