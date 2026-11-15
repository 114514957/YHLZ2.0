# -*- coding: utf-8 -*-
"""干净启动冒烟（不用 pkill 免得杀到自己），并盯 [gradcheck]。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, timeout: int = 120) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


print(sh("cd /root/yh/material_v13 && rm -f smoke60.log && "
         "setsid nohup /root/miniconda3/bin/python -u train_v13.py --config smoke60.json "
         "> smoke60.log 2>&1 < /dev/null & sleep 2; echo '--- started ---'; "
         "ps aux | grep 'train_v13.py' | grep -v grep | head -2"))

DEADLINE = time.time() + 900
state = "?"
while time.time() < DEADLINE:
    log = sh("tail -c 9000 /root/yh/material_v13/smoke60.log 2>/dev/null")
    if "[gradcheck]" in log:
        state = "gradcheck 出现了"
        if "train_runtime" in log:
            break
        time.sleep(15)
        continue
    if "Traceback" in log:
        state = "报错了"
        break
    time.sleep(20)

log = sh("tail -c 16000 /root/yh/material_v13/smoke60.log 2>/dev/null")
print("=" * 76)
print("状态：%s" % state)
print("=" * 76)
keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
        "trainable params", "loss", "Traceback", "Error", "丢弃", "重采样",
        "epoch", "train_runtime")
for line in log.splitlines():
    s = line.strip()
    if any(k in s for k in keys):
        print(s[:160])
cli.close()
