# -*- coding: utf-8 -*-
"""云端跑风格评测：v9t10 vs v9t10-dpo。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30, banner_timeout=30, auth_timeout=30)


def sh(cmd, t=3600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "eval_style.py"), "/root/yh/eval_style.py")
s.close()

for tag, ad in (("v9t10", "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10"),
                ("v9t10-dpo", "/root/autodl-tmp/models/lora/yuanheng-v9t10-dpo")):
    t0 = time.time()
    o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u eval_style.py "
              "--base %s --adapter %s --tag %s 2>&1 | grep -v 'Loading weights' | tail -26"
              % (BASE, ad, tag), t=3600)
    print(o or e)
    print("（%.1f 分钟）\n" % ((time.time() - t0) / 60))
c.close()
