# -*- coding: utf-8 -*-
"""探新实例：GPU / 磁盘 / 有没有基座 / python 环境。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.sha1.seetacloud.com", 22175, "root", "ir253496QXik"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


for label, cmd in (
    ("GPU", "nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader"),
    ("磁盘", "df -h /root/autodl-tmp / | tail -3"),
    ("models", "ls -l /root/autodl-tmp/models/ 2>/dev/null | head -10 || echo 没有 models 目录"),
    ("python", "/root/miniconda3/bin/python -c 'import torch,transformers,peft;print(torch.__version__, transformers.__version__, peft.__version__)' 2>&1 | tail -2"),
    ("内存", "free -g | head -2"),
):
    o, e = sh(cmd)
    print("=== %s ===" % label)
    print((o or e or "（空）")[:600])
    print()
c.close()
