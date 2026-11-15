# -*- coding: utf-8 -*-
"""测我这边拉 128MB 的实际速度：先拉 2MB 估算。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
PACK = "/root/autodl-tmp/pack_v11.tar.gz"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)
s = c.open_sftp()
t0 = time.time()
with s.open(PACK, "rb") as f:
    got = 0
    while got < 2 * 1024 * 1024:
        b = f.read(64 * 1024)
        if not b:
            break
        got += len(b)
dt = time.time() - t0
kbs = got / dt / 1024
print("2MB 用时 %.1f 秒｜%.0f KB/s → 128.5MB 需 %.0f 分钟"
      % (dt, kbs, 134726178 / 1024 / kbs / 60))
s.close()
c.close()
