# -*- coding: utf-8 -*-
"""上传 v13 包 → 建云端 smoke 配置 → 跑冒烟（看 [gradcheck]）。

只做三件事，不做别的：
  1. SFTP 传 dist/v13_pack.tar.gz
  2. 解包到 /root/yh/material_v13
  3. 生成 smoke60 配置（60 条、6 epoch、lr 1e-4）并启动，日志落盘
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
PACK = os.path.join(ROOT, "dist", "v13_pack.tar.gz")
TRAIN = os.path.join(ROOT, "dist", "material_v13", "sft_persona_v13_train.jsonl")

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=30)
sftp = cli.open_sftp()


def run(cmd: str, timeout: int = 300) -> tuple[int, str]:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    return rc, (o + ("\n[err] " + e if e.strip() else ""))


# 1) 上传
run("mkdir -p /root/yh/material_v13")
print("上传 %s（%.1f MB）…" % (os.path.basename(PACK),
                             os.path.getsize(PACK) / 1048576))
t0 = time.time()
sftp.put(PACK, "/root/yh/v13_pack.tar.gz")
print("   完成 %.1f 秒" % (time.time() - t0))

rc, out = run("cd /root/yh && tar xzf v13_pack.tar.gz -C material_v13 && "
              "ls -la material_v13 && md5sum material_v13/*.jsonl", 120)
print(out)

# 2) 生成 smoke60：本地抽样后上传，保证可复现
rows = [ln for ln in io.open(TRAIN, encoding="utf-8", errors="replace") if ln.strip()]
random.Random(20261114).shuffle(rows)
smoke = rows[:60]
smoke_local = os.path.join(ROOT, "dist", "_v13_pack", "smoke60_train.jsonl")
io.open(smoke_local, "w", encoding="utf-8").writelines(smoke)
sftp.put(smoke_local, "/root/yh/material_v13/smoke60_train.jsonl")
print("smoke60：%d 条" % len(smoke))

# 3) smoke 配置（基于 v13 正式配置，只改三样）
cfg = json.load(io.open(os.path.join(ROOT, "dist", "material_v13", "config",
                                     "finetune.gemma4.v13.json"), encoding="utf-8"))
cfg.update({
    "_说明": "v13 冒烟：60 条 × 6 epoch，lr 1e-4。只为验证训练通路与梯度，不用于出分。",
    "base_model": "/root/autodl-tmp/models/gemma-4-e4b-it",
    "train_file": "/root/yh/material_v13/smoke60_train.jsonl",
    "val_file": "/root/yh/material_v13/sft_persona_v13_val.jsonl",
    "output_dir": "/root/autodl-tmp/models/lora/yuanheng-v13-smoke",
    "epochs": 6.0,
    "lr": 0.0001,
    "logging_steps": 5,
})
smoke_cfg = os.path.join(ROOT, "dist", "_v13_pack", "smoke60.json")
io.open(smoke_cfg, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
sftp.put(smoke_cfg, "/root/yh/material_v13/smoke60.json")
print("配置已传：/root/yh/material_v13/smoke60.json")

rc, out = run("cd /root/yh/material_v13 && nohup /root/miniconda3/bin/python -u train_v13.py "
              "--config smoke60.json > smoke60.log 2>&1 & echo started $!", 60)
print(out)
sftp.close()
cli.close()
print("\n下一步：看 /root/yh/material_v13/smoke60.log 里的 [gradcheck]")
