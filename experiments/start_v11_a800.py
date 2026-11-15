# -*- coding: utf-8 -*-
"""A800 上跑 v11：清盘 → 传包 → 依赖 → 预检 → 训练 → 打包。

与 cloud_run_v11.py 的差别：不嵌套调用别的脚本，打包直接在这里做，
更适合这种「盘快满了、基座已就位」的成熟机器。
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v11.tar.gz")
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
PKG = "/root/yh/retrain_pkg_gemma_v11"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v11"
LOG = "/root/autodl-tmp/logs/train_v11.log"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=7200, show=True):
    _i, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").rstrip()
    err = e.read().decode("utf-8", "replace").rstrip()
    if show:
        print(((out + "\n" + err).strip())[:1200])
    return out, err


print("[1] 清盘：删 S2 那个失败的消融模型（15G），v9f1 全量先留")
sh("rm -rf /root/autodl-tmp/models/gemma-4-e4b-it-refusal-ablated; "
   "df -h /root/autodl-tmp | tail -1")

print("\n[2] 传包")
s = c.open_sftp()
sh("mkdir -p /root/yh", show=False)
s.put(TAR, "/root/yh/retrain_pkg_gemma_v11.tar.gz")
s.close()
sh("cd /root/yh && rm -rf retrain_pkg_gemma_v11 && tar -xzf retrain_pkg_gemma_v11.tar.gz "
   "&& wc -l retrain_pkg_gemma_v11/*.jsonl")

print("\n[3] 依赖")
sh("/root/miniconda3/bin/pip install -q 'transformers==5.20.2' 'peft==0.21.2' "
   "'datasets==5.1.0' 'accelerate==1.15.0' 'bitsandbytes==0.50.2' 2>&1 | tail -2", t=1800)

print("\n[4] 预检 MLP")
o, e = sh("cd %s && /root/miniconda3/bin/python preflight_mlp.py %s" % (PKG, BASE), t=1800)
if "PASS" not in (o + e):
    print("❌ 预检没过，停止")
    c.close()
    sys.exit(3)

print("\n[5] 开训")
sh("mkdir -p /root/autodl-tmp/logs && cd %s && "
   "TOKENIZERS_PARALLELISM=false nohup /root/miniconda3/bin/python -u finetune_train.py "
   "--config config/finetune.gemma4.v11.json --base %s > %s 2>&1 & echo LAUNCHED"
   % (PKG, BASE, LOG), t=120)
time.sleep(90)
sh("grep -aE 'trainable params|编码后保留|权重重采样|已冻结|总步数' %s | tail -6; "
   "tail -2 %s" % (LOG, LOG))
print("\n已启动，接下来用 wait_v11.py 轮询。")
c.close()
