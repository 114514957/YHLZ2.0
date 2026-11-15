# -*- coding: utf-8 -*-
"""看 v11 训练实况：进度、loss 走势、val 结果、有没有异常。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
LOG = "/root/autodl-tmp/logs/train_v11.log"

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


print("进程：%s｜GPU：%s" % (q("pgrep -cf '[f]inetune_train.py' || echo 0"),
                          q("nvidia-smi --query-gpu=memory.used,utilization.gpu "
                            "--format=csv,noheader")))
print("显存/盘：%s" % q("df -h /root/autodl-tmp | tail -1"))

raw = q("tr -d '\\r' < %s | grep -aE \"^\\{'loss'|eval_loss|^\\[train\\]|已冻结\" | tail -20" % LOG)
print("\nloss / eval 记录：")
print(raw or "（无）")

raw2 = q("tr -d '\\r' < %s | tail -c 260" % LOG)
print("\n最新一行：\n%s" % raw2[-200:])
c.close()
