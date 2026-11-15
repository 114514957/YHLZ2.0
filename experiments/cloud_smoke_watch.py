# -*- coding: utf-8 -*-
"""看云端冒烟日志：等 [gradcheck] 出现，打印关键行。"""
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


DEADLINE = time.time() + 900          # 最多等 15 分钟
seen_gradcheck = False
while time.time() < DEADLINE:
    log = sh("tail -c 6000 /root/yh/material_v13/smoke60.log 2>/dev/null")
    if "[gradcheck]" in log:
        seen_gradcheck = True
    if "train_runtime" in log or "完成" in log:
        break
    if "Traceback" in log or "Error" in log or "error" in log.lower()[:2000]:
        break
    time.sleep(20)

log = sh("tail -c 12000 /root/yh/material_v13/smoke60.log 2>/dev/null")
print("=" * 74)
print("出现 gradcheck：%s" % ("是" if seen_gradcheck else "还没"))
print("=" * 74)
# 只打关键行
keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
        "trainable params", "loss", "Error", "Traceback", "epoch", "学习率",
        "权重重采样", "丢弃")
for line in log.splitlines():
    s = line.strip()
    if any(k in s for k in keys):
        print(s[:150])

print("\n--- 进程 ---")
print(sh("ps aux | grep -c 'train_v13.py' ; ls -la /root/autodl-tmp/models/lora/ 2>/dev/null | tail -3"))
cli.close()
