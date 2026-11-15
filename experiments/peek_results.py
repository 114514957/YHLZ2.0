# -*- coding: utf-8 -*-
"""看云端评测结果文件 + 训练产物是否完整。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("ls -l /root/yh/results/ 2>/dev/null")
print("结果目录：\n%s" % o)

for f in ("ppl_full.json", "style_v9f1-full.json"):
    o, _ = sh("cat /root/yh/results/%s 2>/dev/null | head -c 600" % f)
    print("\n--- %s ---\n%s" % (f, o or "（没有）"))

o, _ = sh("ls -l /root/autodl-tmp/models/full/yuanheng-v9f1-gemma/ | head -12")
print("\n产物：\n%s" % o)
o, _ = sh("df -h /root/autodl-tmp | tail -1; nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader")
print("磁盘/显存：%s" % o)
c.close()
