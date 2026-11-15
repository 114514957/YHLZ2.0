# -*- coding: utf-8 -*-
"""直接启动 v14 正式训练（冒烟已验证通过）。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nma1.seetacloud.com", port=39522, username="root",
          password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, t: int = 120) -> str:
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


print(sh("cd /root/yh/material_v14 && rm -f v14.log && setsid nohup "
         "/root/miniconda3/bin/python -u train_v13.py --config cfg.json "
         "> v14.log 2>&1 < /dev/null & sleep 3; echo started; "
         "pgrep -af 'train_v13.py --config cfg.json' | head -2"))
c.close()
