# -*- coding: utf-8 -*-
"""查全量训练为什么死的：日志尾部 + 显存 + dmesg OOM。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("tail -c 2500 /root/autodl-tmp/logs/full_v9f1.log")
print("=== 日志尾 ===")
print(o[-2000:])

o, _ = sh("dmesg 2>/dev/null | tail -20 | grep -iE 'oom|killed|memory' || echo 'dmesg 无 OOM 记录（或无权限）'")
print("\n=== dmesg ===")
print(o)

o, _ = sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader; free -g | head -2")
print("\n=== 当前 ===")
print(o)

o, _ = sh("ls -l /root/autodl-tmp/models/full/yuanheng-v9f1-gemma/ 2>/dev/null")
print("\n=== 产物目录 ===")
print(o)
c.close()
