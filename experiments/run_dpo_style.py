# -*- coding: utf-8 -*-
"""上传 DPO 数据与脚本，云端开练。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
ADAPTER = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v9t10-dpo"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=10800):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


print("== 检查有没有 v9t10 的 adapter ==")
o, _ = sh("ls -l %s/ 2>/dev/null | head -4 || echo 没有" % ADAPTER)
print(o)

s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "dpo_style.py"), "/root/yh/dpo_style.py")
sh("mkdir -p /root/yh/dpo_style_v1")
for f in ("train.jsonl", "val.jsonl"):
    s.put(os.path.join(YH, "dist", "dpo_style_v1", f), "/root/yh/dpo_style_v1/" + f)
s.close()
print("\n数据与脚本已上传")

print("\n== 装 trl ==")
o, e = sh("/root/miniconda3/bin/pip install -q 'trl>=0.12' 2>&1 | tail -3; "
          "/root/miniconda3/bin/python -c 'import trl; print(\"trl\", trl.__version__)'", t=1800)
print(o or e)

print("\n== 开练 ==")
t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u dpo_style.py "
          "--base %s --adapter %s --data /root/yh/dpo_style_v1 --out %s "
          "--beta 0.1 --lr 5e-5 --epochs 1 2>&1 | grep -v 'Loading weights' | tail -35"
          % (BASE, ADAPTER, OUT), t=10800)
print(o or e)
print("\nDPO 用时 %.1f 分钟" % ((time.time() - t0) / 60))
c.close()
