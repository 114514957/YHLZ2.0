# -*- coding: utf-8 -*-
"""看正式训练进度（轻量）。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nma1.seetacloud.com", port=39522, username="root",
          password="FSMqu7B3fRXc", timeout=30)
_i, o, _e = c.exec_command("tail -c 1200 /root/yh/material_v13/v13.log", timeout=60)
t = o.read().decode("utf-8", "replace")
c.close()

steps = re.findall(r"(\d+)/706", t)
losses = re.findall(r"'loss': '([\d.]+)'", t)
print("进度：%s / 706" % (steps[-1] if steps else "?"))
print("最近 loss：%s" % (losses[-3:] or "?"))
print("已结束：" , "train_runtime" in t)
