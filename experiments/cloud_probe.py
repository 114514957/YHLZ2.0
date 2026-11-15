# -*- coding: utf-8 -*-
"""连云端：确认 GPU / 磁盘 / 环境（只读，不改东西）。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import paramiko  # noqa: E402

HOST, PORT, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=25,
            banner_timeout=25, auth_timeout=25)
print("✅ 已连上 %s:%d" % (HOST, PORT))

CMDS = [
    ("GPU", "nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader"),
    ("磁盘", "df -h /root | tail -1"),
    ("内存", "free -g | head -2"),
    ("Python", "python -V 2>&1; which python; which pip"),
    ("已装包", "python -c 'import torch,transformers;print(\"torch\",torch.__version__,\"cuda\",torch.cuda.is_available());print(\"transformers\",transformers.__version__)' 2>&1 | tail -3"),
    ("目录", "ls -la /root | head -12"),
    ("autodl盘", "ls -d /root/autodl-tmp 2>/dev/null && df -h /root/autodl-tmp | tail -1"),
]
for label, cmd in CMDS:
    _in, out, err = cli.exec_command(cmd, timeout=60)
    o = out.read().decode("utf-8", "replace").strip()
    e = err.read().decode("utf-8", "replace").strip()
    print("\n=== %s ===" % label)
    print(o or "(空)")
    if e:
        print("[err] " + e[:300])
cli.close()
