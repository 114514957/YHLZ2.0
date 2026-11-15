# -*- coding: utf-8 -*-
"""确认正式训练是否在跑：进程 / 日志 / 输出目录。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, timeout: int = 60) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


print("=== 进程 ===")
print(sh("pgrep -af 'train_v13.py' || echo '(没有进程)'"))
print("=== 日志行数/末尾 ===")
print(sh("wc -l -c /root/yh/material_v13/v13.log 2>/dev/null; tail -6 /root/yh/material_v13/v13.log 2>/dev/null"))
print("=== 输出目录 ===")
print(sh("ls -la /root/autodl-tmp/models/lora/yuanheng-v13 2>/dev/null | tail -5 || echo '(还没建)'"))
print("=== 显存 ===")
print(sh("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader"))
cli.close()
