# -*- coding: utf-8 -*-
"""逐步确认：云端文件到底改了没、有没有旧进程、日志是谁写的。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=120)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


print("=== 1. 云端 smoke60.json 里的 attn ===")
print(sh("grep -n attn_implementation /root/yh/material_v13/smoke60.json"))

print("=== 2. 云端 train_v13.py 里的默认值 ===")
print(sh("grep -n 'attn_implementation' /root/yh/material_v13/train_v13.py"))

print("=== 3. 文件时间戳（确认是我刚传的）===")
print(sh("ls -la --time-style=full-iso /root/yh/material_v13/train_v13.py "
         "/root/yh/material_v13/smoke60.json"))

print("=== 4. 还有没有 train_v13 进程 ===")
print(sh("ps aux | grep train_v13 | grep -v grep || echo '(无)'"))

print("=== 5. 日志开头 12 行（看是谁写的）===")
print(sh("head -12 /root/yh/material_v13/smoke60.log"))
cli.close()
