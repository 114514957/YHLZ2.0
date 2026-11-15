# -*- coding: utf-8 -*-
"""云端跑 S2 原文展示。"""
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
s.put(os.path.join(YH, "experiments", "s2_show.py"), "/root/yh/s2_show.py")
s.close()

t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u s2_show.py "
          "--base /root/autodl-tmp/models/gemma-4-e4b-it --lams 0,20,50,100 "
          "2>&1 | grep -v 'Loading weights' | tail -40", t=7200)
print(o or e)
print("\n用时 %.1f 分钟" % ((time.time() - t0) / 60))
c.close()
