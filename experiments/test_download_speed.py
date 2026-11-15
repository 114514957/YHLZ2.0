# -*- coding: utf-8 -*-
"""1) 杀掉卡住的等待进程  2) 测 12 路并行下载速度（取前 200MB）"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
REMOTE = "/root/autodl-tmp/models/full/yuanheng-v9f1-gemma/model.safetensors"
N = 12
TEST = 200 * 1024 * 1024

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)
    return c


got = [0] * N
step = TEST // N


def work(i):
    start = i * step
    end = start + step - 1
    buf = bytearray()
    try:
        c = conn()
        s = c.open_sftp()
        rf = s.open(REMOTE, "rb")
        rf.seek(start)
        left = end - start + 1
        while left > 0:
            b = rf.read(min(1 << 20, left))
            if not b:
                break
            left -= len(b)
            buf.extend(b)
            got[i] = step - left
        rf.close()
        s.close()
        c.close()
    except Exception as ex:  # noqa: BLE001
        print("  [p%d] %s" % (i, type(ex).__name__))


ths = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(N)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join()
dt = time.time() - t0
tot = sum(got)
print("12 路：%.1f MB / %.1f 秒 = **%.2f MB/s**" % (tot / 1e6, dt, tot / 1e6 / dt))
print("15.88GB 预计 %.0f 分钟" % (15882 / (tot / 1e6 / dt) / 60))
