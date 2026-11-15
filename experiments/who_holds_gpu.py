# -*- coding: utf-8 -*-
"""查是谁占着 GPU、以及训练进程到底怎么没的。"""
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


for label, cmd in (
    ("GPU 占用进程", "nvidia-smi --query-compute-apps=pid,process_name,used_memory "
                    "--format=csv,noheader"),
    ("python 进程", "ps aux | grep -c '[p]ython'"),
    ("训练相关", "ps aux | grep '[f]inetune_train' | head -2"),
    ("日志里有没有 Killed", "grep -aiE 'killed|error|traceback|out of memory' "
                            "/root/autodl-tmp/logs/full_v9f1.log | tail -5"),
    ("系统内存", "free -g | head -2"),
    ("磁盘", "df -h /root/autodl-tmp | tail -1"),
):
    o, e = sh(cmd)
    print("=== %s ===" % label)
    print((o or e or "（空）")[:500])
    print()
c.close()
