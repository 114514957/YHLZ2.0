# -*- coding: utf-8 -*-
"""云端快速评测全量微调模型：遗忘检查（PPL）+ 风格三项。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
M = "/root/autodl-tmp/models/full/yuanheng-v9f1-gemma"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=3600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


print("== 遗忘检查（训练后 PPL，基线 2199.72）==")
t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u ppl_probe.py --model %s --tag full "
          "2>&1 | grep -v 'Loading weights' | tail -3" % M, t=3600)
print(o or e)
print("（%.1f 分钟）" % ((time.time() - t0) / 60))

print("\n== 风格三项 ==")
t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u eval_style.py --base %s --tag v9f1-full "
          "2>&1 | grep -v 'Loading weights' | head -14" % M, t=3600)
print(o or e)
print("（%.1f 分钟）" % ((time.time() - t0) / 60))
c.close()
