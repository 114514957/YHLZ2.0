# -*- coding: utf-8 -*-
"""在云端后台起「8 路并行下基座」，用 setsid 脱离 SSH 通道，避免 exec 卡住。"""
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


def sh(cmd, t=120):
    _i, o, e = c.exec_command(cmd, timeout=t)
    try:
        return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()
    except Exception as ex:  # noqa: BLE001
        return "", str(ex)


# 用 setsid + 全重定向，让子进程彻底脱离当前通道
o, e = sh("pkill -f fetch_base_parallel || true; pkill -f 'curl.*model.safetensors' || true; "
          "cd /root/yh && ( setsid bash fetch_base_parallel.sh >/root/autodl-tmp/logs/fetch_base.log 2>&1 </dev/null & ) ; "
          "sleep 2; echo STARTED", t=60)
print("启动结果：%r %r" % (o, e))

time.sleep(10)
o, _ = sh("pgrep -fc curl || echo 0")
print("在跑的 curl 进程数：%s" % o)
o, _ = sh("head -3 /root/autodl-tmp/logs/fetch_base.log 2>/dev/null")
print("日志头：\n%s" % o)
c.close()
