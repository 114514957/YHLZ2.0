# -*- coding: utf-8 -*-
"""直接看云端冒烟日志原样（不过滤），判断它在哪一步。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, timeout: int = 120) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


print("=== 日志行数 / 字节 ===")
print(sh("wc -l -c /root/yh/material_v13/smoke60.log"))
print("=== 全部日志（末 40 行）===")
print(sh("tail -40 /root/yh/material_v13/smoke60.log"))
print("=== 进程与显存 ===")
print(sh("ps -o pid,etime,%cpu,%mem,cmd -p $(pgrep -f train_v13.py | head -1) 2>/dev/null; "
         "nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader"))
cli.close()
