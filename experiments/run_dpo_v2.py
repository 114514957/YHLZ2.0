# -*- coding: utf-8 -*-
"""云端：用 v2 数据重练 DPO（不改 runner，直接传参）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
ADAPTER = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v9t10-dpo2"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=10800):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "dpo_style.py"), "/root/yh/dpo_style.py")
sh("mkdir -p /root/yh/dpo_style_v2")
for f in ("train.jsonl", "val.jsonl"):
    s.put(os.path.join(YH, "dist", "dpo_style_v2", f), "/root/yh/dpo_style_v2/" + f)
s.close()
print("v2 数据已上传")

t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u dpo_style.py "
          "--base %s --adapter %s --data /root/yh/dpo_style_v2 --out %s "
          "--beta 0.1 --lr 5e-5 --epochs 1 2>&1 | grep -v 'Loading weights' | tail -12"
          % (BASE, ADAPTER, OUT), t=10800)
print(o or e)
print("训练 %.1f 分钟" % ((time.time() - t0) / 60))

# 直接在同一台机器上评风格
print("\n== 风格评测 ==")
for tag, ad in (("v9t10-dpo2", OUT),):
    o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u eval_style.py "
              "--base %s --adapter %s --tag %s 2>&1 | grep -v 'Loading weights' | head -14"
              % (BASE, ad, tag), t=3600)
    print(o or e)
c.close()
