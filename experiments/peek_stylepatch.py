# -*- coding: utf-8 -*-
"""短查询：stylepatch 训完没、GGUF 转没、包打没。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)


def q(cmd, t=90):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


print("进程：%s" % q("pgrep -cf '[f]inetune_train.py' || echo 0"))
print("adapter：%s" % q("ls -l /root/autodl-tmp/models/lora/yuanheng-stylepatch4/adapter_model.safetensors 2>/dev/null || echo 无"))
print("gguf：%s" % q("ls -l /root/autodl-tmp/yuanheng-stylepatch4-lora.gguf 2>/dev/null || echo 无"))
print("包：%s" % q("ls -l /root/autodl-tmp/pack_stylepatch4.tar.gz 2>/dev/null || echo 无"))
print("日志尾：%s" % q("tail -c 220 /root/autodl-tmp/logs/train_stylepatch4.log | tr -d '\\r'"))
c.close()
