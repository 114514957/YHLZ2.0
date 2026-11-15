# -*- coding: utf-8 -*-
"""开卡先探：GPU / 磁盘 / 基座在不在 / 上次的产物占多少。"""
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
    ("GPU", "nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader"),
    ("磁盘", "df -h /root/autodl-tmp | tail -1"),
    ("models", "du -sh /root/autodl-tmp/models/* 2>/dev/null"),
    ("基座", "test -f /root/autodl-tmp/models/gemma-4-e4b-it/model.safetensors && "
            "ls -l /root/autodl-tmp/models/gemma-4-e4b-it/model.safetensors || echo MISSING"),
    ("root盘", "du -sh /root/autodl-tmp/* 2>/dev/null | sort -h | tail -6"),
):
    o, e = sh(cmd)
    print("=== %s ===" % label)
    print((o or e or "（空）")[:700])
    print()
c.close()
