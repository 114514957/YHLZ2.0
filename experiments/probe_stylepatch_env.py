# -*- coding: utf-8 -*-
"""开 stylepatch 前：确认云上有 dpo2 adapter、盘够、基座在。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)


def q(cmd, t=120):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


print("GPU：%s" % q("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"))
print("盘：%s" % q("df -h /root/autodl-tmp | tail -1"))
print("\nlora 目录：\n%s" % q("ls -l /root/autodl-tmp/models/lora/ | head -12"))
print("\ndpo2 adapter：%s" % q(
    "test -f /root/autodl-tmp/models/lora/yuanheng-v9t10-dpo2/adapter_model.safetensors "
    "&& ls -l /root/autodl-tmp/models/lora/yuanheng-v9t10-dpo2/adapter_model.safetensors "
    "|| echo MISSING"))
print("\n基座：%s" % q("test -f /root/autodl-tmp/models/gemma-4-e4b-it/model.safetensors "
                     "&& echo OK || echo MISSING"))
c.close()
