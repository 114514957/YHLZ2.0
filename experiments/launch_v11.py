# -*- coding: utf-8 -*-
"""包已上传并解开，跑最后三步：依赖 → 预检 → 开训。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
PKG = "/root/yh/retrain_pkg_gemma_v11"
LOG = "/root/autodl-tmp/logs/train_v11.log"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)
c.get_transport().set_keepalive(15)


def sh(cmd, t=7200):
    _i, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").rstrip()
    err = e.read().decode("utf-8", "replace").rstrip()
    return out, err


print("[1/3] 依赖")
o, e = sh("/root/miniconda3/bin/pip install -q 'transformers==5.20.2' 'peft==0.21.2' "
          "'datasets==5.1.0' 'accelerate==1.15.0' 'bitsandbytes==0.50.2' 2>&1 | tail -2", t=3600)
print((o + e)[-400:] or "  已装好")

print("\n[2/3] 预检 MLP")
o, e = sh("cd %s && /root/miniconda3/bin/python preflight_mlp.py %s" % (PKG, BASE), t=1800)
print((o + "\n" + e).strip()[:800])
if "PASS" not in (o + e):
    c.close()
    sys.exit("预检没过，停")

print("\n[3/3] 开训")
sh("mkdir -p /root/autodl-tmp/logs && cd %s && "
   "TOKENIZERS_PARALLELISM=false setsid nohup /root/miniconda3/bin/python -u finetune_train.py "
   "--config config/finetune.gemma4.v11.json --base %s > %s 2>&1 < /dev/null & echo LAUNCHED"
   % (PKG, BASE, LOG), t=120)
time.sleep(150)
o, _ = sh("grep -aE 'trainable params|编码后保留|权重重采样|已冻结' %s | tail -6; "
          "tail -c 300 %s" % (LOG, LOG))
print(o)
c.close()
