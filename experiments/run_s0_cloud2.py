# -*- coding: utf-8 -*-
"""上传语料 + 新 S0，重跑（真实语料 + float64 累加）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=7200):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "s0_rank_diagnosis.py"), "/root/yh/s0_rank_diagnosis.py")
s.put(os.path.join(YH, "cache", "s0_corpus.txt"), "/root/yh/s0_corpus.txt")
s.close()
print("已上传脚本与语料（%.1f MB）" % (os.path.getsize(os.path.join(YH, "cache", "s0_corpus.txt")) / 1e6))

t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u s0_rank_diagnosis.py "
          "--base /root/autodl-tmp/models/gemma-4-e4b-it "
          "--out /root/yh/results/s0.json --max-tokens 50000 "
          "--corpus /root/yh/s0_corpus.txt 2>&1 | grep -v 'Loading weights' | tail -45", t=7200)
print(o or e)
print("\n用时 %.1f 分钟" % ((time.time() - t0) / 60))
o, _ = sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader")
print("显存：" + o)
c.close()
