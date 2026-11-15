# -*- coding: utf-8 -*-
"""腾磁盘：删已保存的 checkpoint-300（save_total_limit=1，到 600 也会被覆盖），
再看训练到底跑到第几步。"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("ls -d /root/autodl-tmp/models/full/yuanheng-v9f1-gemma/checkpoint-* 2>/dev/null")
print("现有 checkpoint：%s" % (o or "（无）"))
if "checkpoint-300" in o:
    o2, _ = sh("rm -rf /root/autodl-tmp/models/full/yuanheng-v9f1-gemma/checkpoint-300; "
               "df -h /root/autodl-tmp | tail -1")
    print("删掉 checkpoint-300 → %s" % o2)

o, _ = sh("tail -c 1200 /root/autodl-tmp/logs/full_v9f1.log")
m = re.findall(r"(\d+)/935 \[([0-9:]+)<([0-9:]+)", o)
if m:
    n, el, eta = m[-1]
    print("\n进度 %s/935｜已用 %s｜剩余 %s" % (n, el, eta))
o, _ = sh("ps -o etime=,time= -p $(pgrep -f '[f]inetune_train.py' | head -1)")
print("进程运行时长/CPU：%s" % o)
o, _ = sh("df -h /root/autodl-tmp | tail -1; nvidia-smi --query-gpu=memory.free --format=csv,noheader")
print("磁盘/显存：%s" % o)
c.close()
