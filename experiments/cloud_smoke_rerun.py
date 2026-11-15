# -*- coding: utf-8 -*-
"""重传改好的 train_v13.py + smoke60.json，重跑冒烟，盯 [gradcheck]。"""
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


def sh(cmd: str, timeout: int = 180) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


for local, remote in (
        (os.path.join(ROOT, "dist", "material_v13", "train_v13.py"),
         "/root/yh/material_v13/train_v13.py"),
        (os.path.join(ROOT, "dist", "_v13_pack", "smoke60.json"),
         "/root/yh/material_v13/smoke60.json")):
    sftp.put(local, remote)
    print("已传 %s" % remote)

print(sh("cd /root/yh/material_v13 && pkill -f train_v13.py; sleep 1; "
         "grep -o '\"attn_implementation\": *\"[a-z]*\"' smoke60.json; "
         "nohup /root/miniconda3/bin/python -u train_v13.py --config smoke60.json "
         "> smoke60.log 2>&1 & echo started", 120))

DEADLINE = time.time() + 900
ok = False
while time.time() < DEADLINE:
    log = sh("tail -c 8000 /root/yh/material_v13/smoke60.log 2>/dev/null")
    if "[gradcheck]" in log:
        ok = True
        break
    if "Traceback" in log:
        break
    time.sleep(20)

log = sh("tail -c 14000 /root/yh/material_v13/smoke60.log 2>/dev/null")
print("=" * 74)
print("gradcheck 出现：%s" % ("是 ✅" if ok else "否 ❌"))
print("=" * 74)
keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
        "trainable params", "'loss'", "Traceback", "Error", "丢弃", "重采样")
for line in log.splitlines():
    s = line.strip()
    if any(k in s for k in keys):
        print(s[:150])
sftp.close()
cli.close()
