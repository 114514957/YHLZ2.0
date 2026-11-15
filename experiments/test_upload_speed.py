# -*- coding: utf-8 -*-
"""测本机→云端 SFTP 上传速度（200MB 随机数据），决定走不走「本地下+上传」。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TMP = os.path.join(r"C:\\Users\\ACE_WAN——PROJECT\\YHLZ\\YH\\cache", "_up_test.bin")

if not os.path.exists(TMP) or os.path.getsize(TMP) < 200 * 1024 * 1024:
    with open(TMP, "wb") as f:
        for _ in range(200):
            f.write(os.urandom(1024 * 1024))
print("测试文件 %.0f MB" % (os.path.getsize(TMP) / 1048576))

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)
s = c.open_sftp()
t0 = time.time()
s.put(TMP, "/root/autodl-tmp/_up_test.bin")
dt = time.time() - t0
mb = os.path.getsize(TMP) / 1048576
print("上传 %.0f MB / %.1f 秒 = **%.2f MB/s**" % (mb, dt, mb / dt))
print("15GB 预计 %.0f 分钟" % (15000 / (mb / dt) / 60))
s.remove("/root/autodl-tmp/_up_test.bin")
s.close()
c.close()
os.remove(TMP)
