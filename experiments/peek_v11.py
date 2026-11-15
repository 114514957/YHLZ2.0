# -*- coding: utf-8 -*-
"""不阻塞地查 v11 状态：不读 stdout，只看远端文件与进程。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
LOG = "/root/autodl-tmp/logs/train_v11.log"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)


def quick(cmd):
    _i, o, e = c.exec_command(cmd, timeout=60)
    o.channel.settimeout(50)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception as ex:  # noqa: BLE001
        return "[读超时 %s]" % type(ex).__name__


print("进程数：%s" % quick("pgrep -cf '[f]inetune_train.py' || echo 0"))
print("GPU：%s" % quick("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader"))
print("日志存在：%s" % quick("test -f %s && echo YES || echo NO" % LOG))
print("\n日志尾部：\n%s" % quick("tail -c 600 %s 2>/dev/null" % LOG))
c.close()
