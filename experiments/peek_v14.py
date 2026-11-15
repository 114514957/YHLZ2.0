# -*- coding: utf-8 -*-
"""看 v14 冒烟/正式训练日志（原样关键行）。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, timeout: int = 90) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


for name, path in (("冒烟", "/root/yh/material_v14/smoke.log"),
                  ("正式", "/root/yh/material_v14/v14.log")):
    print("=" * 70)
    print("### %s：%s" % (name, path))
    log = sh("tail -c 6000 %s 2>/dev/null || echo '(无日志)'" % path)
    keys = ("attn_implementation", "enable_input_require_grads", "gradcheck",
            "trainable params", "loss", "Traceback", "RuntimeError",
            "总步数", "train_runtime", "丢弃", "重采样")
    shown = 0
    for line in log.splitlines():
        s = line.strip()
        if any(k in s for k in keys):
            print("   " + s[:150])
            shown += 1
    if not shown:
        print("   （还没输出关键行）")
    steps = re.findall(r"(\d+)/(\d+)", log)
    if steps:
        print("   进度：%s" % steps[-1])
print("\n=== 进程 ===")
print(sh("pgrep -af 'train_v13.py' | head -3 || echo '(无)'"))
cli.close()
