# -*- coding: utf-8 -*-
"""直链下基座（绕开 HF API 限流），完成后再起训。"""
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


def sh(cmd, t=3600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "fetch_base.sh"), "/root/yh/fetch_base.sh")
s.close()
print("脚本已上传，开始下载基座（14.9 GiB）…\n")

o, e = sh("cd /root/yh && chmod +x fetch_base.sh && bash fetch_base.sh 2>&1 | tail -30", t=3600)
print(o or e)

o, _ = sh("df -h /root/autodl-tmp | tail -1")
print("\n磁盘：" + o)
c.close()
