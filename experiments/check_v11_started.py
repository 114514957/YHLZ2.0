# -*- coding: utf-8 -*-
"""查 v11 训练到底起没起。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
LOG = "/root/autodl-tmp/logs/train_v11.log"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("ls -l /root/yh/retrain_pkg_gemma_v11/*.jsonl 2>/dev/null | head -3; "
          "pgrep -c '[f]inetune_train.py' || echo 0; "
          "nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader; "
          "df -h /root/autodl-tmp | tail -1")
print(o)

o, _ = sh("test -f %s && tail -c 800 %s || echo 没有日志" % (LOG, LOG))
print("\n日志：\n%s" % o[-700:])

m = re.findall(r"(\d+)/1649", o)
print("\n步数线索：%s" % (m[-1] if m else "无"))
c.close()
