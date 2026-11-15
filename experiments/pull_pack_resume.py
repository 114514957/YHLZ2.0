# -*- coding: utf-8 -*-
"""可断点续传的后台下 128MB 包。断了自动从断点继续，直到大小与 sha 都对。"""
from __future__ import annotations

import hashlib
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
PACK = "/root/autodl-tmp/pack_v11.tar.gz"
LOCAL = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\pack_v11.tar.gz"
WANT = 134726178
SHA = "a7f1f01d982aaca79580de805fa79009c90e1268a4f40fdc586270e6726642df"

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


t0 = time.time()
for attempt in range(1, 41):
    have = os.path.getsize(LOCAL) if os.path.exists(LOCAL) else 0
    if have >= WANT:
        break
    try:
        c = conn()
        s = c.open_sftp()
        with s.open(PACK, "rb") as f, open(LOCAL, "ab") as out:
            f.seek(have)
            got = have
            t_req = time.time()
            while got < WANT:
                b = f.read(256 * 1024)
                if not b:
                    break
                out.write(b)
                got += len(b)
                if got - have >= 8 * 1024 * 1024:
                    out.flush()
                    rate = (got - have) / max(1e-6, time.time() - t_req) / 1024
                    print("  [%d] %.1f/128.5 MB｜%.0f KB/s｜第 %d 次"
                          % (attempt, got / 1048576, rate, attempt), flush=True)
                    have, t_req = got, time.time()
        s.close()
        c.close()
    except Exception as ex:  # noqa: BLE001
        print("  断在 %.1f MB（%s），10 秒后续传"
              % (os.path.getsize(LOCAL) / 1048576 if os.path.exists(LOCAL) else 0,
                 type(ex).__name__), flush=True)
        time.sleep(10)

size = os.path.getsize(LOCAL) if os.path.exists(LOCAL) else 0
print("\n完成：%d/%d 字节｜%.0f 分钟" % (size, WANT, (time.time() - t0) / 60), flush=True)
if size == WANT:
    h = hashlib.sha256()
    with open(LOCAL, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    print("sha256 %s｜一致：%s" % (h.hexdigest()[:16], h.hexdigest() == SHA), flush=True)
