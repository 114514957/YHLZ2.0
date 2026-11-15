# -*- coding: utf-8 -*-
"""云端：评测 base 与 ablated 两版（拒答率 + 困惑度）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=7200):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "eval_ablated.py"), "/root/yh/eval_ablated.py")
s.close()

for tag, model in (("base", "/root/autodl-tmp/models/gemma-4-e4b-it"),
                   ("ablated", "/root/autodl-tmp/models/gemma-4-e4b-it-refusal-ablated")):
    t0 = time.time()
    o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u eval_ablated.py "
              "--model %s --tag %s 2>&1 | grep -v 'Loading weights' | tail -12"
              % (model, tag), t=7200)
    print("=== %s（%.1f 分钟）===" % (tag, (time.time() - t0) / 60))
    print(o or e)
    print()
c.close()
