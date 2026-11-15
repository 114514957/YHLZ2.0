# -*- coding: utf-8 -*-
"""诊断 + 换通道上传：SFTP 全断时改走 exec stdin（cat > file）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v11.tar.gz")
REMOTE = "/root/yh/retrain_pkg_gemma_v11.tar.gz"
WANT = os.path.getsize(TAR)

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


print("1) 连通性")
c = conn()
print(c.exec_command("echo ALIVE; uptime | head -1")[1].read().decode().strip())

print("\n2) 远端目录可写？")
_i, o, e = c.exec_command("touch /root/yh/_wtest && echo WRITABLE && rm -f /root/yh/_wtest")
print((o.read() + e.read()).decode().strip())

print("\n3) 试 SFTP 传 1KB")
try:
    s = c.open_sftp()
    s.putfo(__import__("io").BytesIO(b"x" * 1024), "/root/yh/_sftptest.bin")
    print("   1KB 成功｜远端大小 %d" % s.stat("/root/yh/_sftptest.bin").st_size)
    s.remove("/root/yh/_sftptest.bin")
    s.close()
except Exception as ex:  # noqa: BLE001
    print("   1KB 也失败：%s: %s" % (type(ex).__name__, ex))
c.close()

print("\n4) 走 exec stdin 传整包（%.2f MB）" % (WANT / 1e6))
t0 = time.time()
c = conn()
_i, o, e = c.exec_command("cat > %s" % REMOTE, timeout=1800)
data = open(TAR, "rb").read()
try:
    i = c.get_transport().open_session()  # noqa: F841
except Exception:  # noqa: BLE001
    pass
# 用 exec_command 返回的 stdin 写
stdin = c.exec_command("cat > %s" % REMOTE, timeout=1800)[0]
stdin.write(data)
stdin.channel.shutdown_write()
time.sleep(2)
_i2, o2, e2 = c.exec_command("stat -c %%s %s" % REMOTE)
have = o2.read().decode().strip()
print("   写入后大小：%s（应 %d）｜用时 %.0f 秒" % (have, WANT, time.time() - t0))
c.close()
