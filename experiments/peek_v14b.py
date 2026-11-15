# -*- coding: utf-8 -*-
"""看 v14 正式训练是否在跑、进度、loss。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nma1.seetacloud.com", port=39522, username="root",
          password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, t: int = 90) -> str:
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


print("进程：", sh("pgrep -af 'train_v13.py' | head -3 || echo 无").strip() or "无")
log = sh("tail -c 3000 /root/yh/material_v14/v14.log 2>/dev/null || echo '(无日志)'")
steps = re.findall(r"(\d+)/706", log)
losses = re.findall(r"'loss': '([\d.]+)'", log)
print("进度：", (steps[-1] + "/706") if steps else "（尚未开始或已结束）")
print("最近 loss：", losses[-3:] or "—")
print("gradcheck：", "有" if "[gradcheck]" in log else "还没")
print("完成：", "是" if "train_runtime" in log else "否")
print("\n--- 尾部 ---")
print(log[-500:])
c.close()
