# -*- coding: utf-8 -*-
"""重传训练器，重跑冒烟，等 [gradcheck] 出非零数字。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)
sftp = cli.open_sftp()


def sh(cmd: str, timeout: int = 150) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


sftp.put(os.path.join(ROOT, "dist", "material_v13", "train_v13.py"),
         "/root/yh/material_v13/train_v13.py")
print("训练器已重传")
print(sh("cd /root/yh/material_v13 && rm -f smoke60.log && "
         "setsid nohup /root/miniconda3/bin/python -u train_v13.py --config smoke60.json "
         "> smoke60.log 2>&1 < /dev/null & sleep 2; echo started"))

DEADLINE = time.time() + 780
got = False
while time.time() < DEADLINE:
    log = sh("tail -c 9000 /root/yh/material_v13/smoke60.log 2>/dev/null")
    if "[gradcheck]" in log:
        got = True
        if "train_runtime" in log or "RuntimeError" in log:
            break
    if "RuntimeError" in log:
        break
    time.sleep(20)

log = sh("tail -c 16000 /root/yh/material_v13/smoke60.log 2>/dev/null")
print("=" * 76)
print("gradcheck 出现：%s" % ("是 ✅" if got else "否 ❌"))
print("=" * 76)
keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
        "trainable params", "loss", "RuntimeError", "Traceback",
        "丢弃", "重采样", "train_runtime")
for line in log.splitlines():
    s = line.strip()
    if any(k in s for k in keys):
        print(s[:160])
sftp.close()
cli.close()
