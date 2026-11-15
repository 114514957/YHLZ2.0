# -*- coding: utf-8 -*-
"""网络不稳时的上传：xz 压小 → 切成 256KB 片 → 每片走 exec stdin 追加 → 末了校验 sha256。

比 SFTP 整包传更适合烂网：单片失败只重传那一片，不用从头来。
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(YH, "dist", "retrain_pkg_gemma_v11")
REMOTE_DIR = "/root/yh"
CHUNK = 256 * 1024

import paramiko  # noqa: E402

# 1) xz 压缩（用 Python 自带 lzma，Windows 没有 xz 命令）
base = os.path.basename(SRC.rstrip("\\/"))
xz = os.path.join(YH, "cache", base + ".tar.xz")
print("[1] 压缩成 xz…", flush=True)
import tarfile  # noqa: E402
with tarfile.open(xz, "w:xz", preset=9) as tf:
    tf.add(SRC, arcname=base)
size = os.path.getsize(xz)
sha = hashlib.sha256(open(xz, "rb").read()).hexdigest()
gz_path = os.path.join(YH, "dist", base + ".tar.gz")
gz_size = os.path.getsize(gz_path) if os.path.exists(gz_path) else 0
print("    %s｜%.2f MB（gz 是 %.2f MB）｜sha256 %s"
      % (os.path.basename(xz), size / 1e6, gz_size / 1e6, sha[:16]), flush=True)

data = open(xz, "rb").read()
parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
print("    切成 %d 片（每片 %d KB）" % (len(parts), CHUNK // 1024), flush=True)


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


remote = "%s/%s.tar.xz" % (REMOTE_DIR, base)
c = conn()
c.exec_command("rm -f %s" % remote)[1].read()
c.close()

print("\n[2] 逐片上传", flush=True)
t0 = time.time()
sent = 0
for idx, part in enumerate(parts):
    done = False
    for attempt in range(1, 6):
        try:
            c = conn()
            stdin, _o, _e = c.exec_command("cat >> %s" % remote, timeout=600)
            stdin.write(part)
            stdin.channel.shutdown_write()
            stdin.channel.recv_exit_status()
            c.close()
            sent += len(part)
            done = True
            break
        except Exception as ex:  # noqa: BLE001
            print("    片 %d/%d 第 %d 次失败：%s" % (idx + 1, len(parts), attempt,
                                                  type(ex).__name__), flush=True)
            time.sleep(2)
            # 回滚这一片（远端可能收了一半）
            try:
                c2 = conn()
                c2.exec_command("truncate -s %d %s" % (sent, remote))[1].read()
                c2.close()
            except Exception:  # noqa: BLE001
                pass
    if not done:
        sys.exit("片 %d 传不上去，先停" % (idx + 1))
    if (idx + 1) % 4 == 0 or idx + 1 == len(parts):
        print("    %d/%d 片｜%.1f%%｜%.0f 秒"
              % (idx + 1, len(parts), 100 * sent / size, time.time() - t0), flush=True)

print("\n[3] 校验", flush=True)
c = conn()
_o, o, _e = c.exec_command("stat -c %%s %s; sha256sum %s | cut -d' ' -f1" % (remote, remote))
lines = o.read().decode().split()
c.close()
have_size = int(lines[0]) if lines else 0
have_sha = lines[1] if len(lines) > 1 else ""
print("    远端 %d 字节（应 %d）｜sha256 一致：%s" % (have_size, size, have_sha == sha))
if have_size != size or have_sha != sha:
    sys.exit("校验不过，别解包")

print("\n[4] 解开", flush=True)
c = conn()
_i, o, e = c.exec_command("cd %s && rm -rf %s && tar -xJf %s.tar.xz && wc -l %s/*.jsonl"
                          % (REMOTE_DIR, base, base, base), timeout=600)
print((o.read().decode() + e.read().decode()).strip())
c.close()
print("\n完成：%s/%s" % (REMOTE_DIR, base))
