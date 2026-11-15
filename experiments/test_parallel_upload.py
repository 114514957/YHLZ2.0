# -*- coding: utf-8 -*-
"""测 8 路并行上传速度：取模型前 1GB 上传，量完删掉。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "models", "gemma4-hf", "gemma-4-E4B-it-uncensored",
                   "model.safetensors")
SLICE = os.path.join(YH, "cache", "_slice1g.bin")
N = 1 << 30

if not os.path.exists(SLICE) or os.path.getsize(SLICE) != N:
    with open(SRC, "rb") as f, open(SLICE, "wb") as g:
        g.write(f.read(N))
print("切片 %.2f GB" % (os.path.getsize(SLICE) / 1e9))

t0 = time.time()
r = subprocess.run([sys.executable, os.path.join(YH, "experiments", "parallel_upload.py"),
                    SLICE, "/root/autodl-tmp/_slice1g.bin", "8"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
dt = time.time() - t0
print(r.stdout[-1200:], r.stderr[-400:])
mb = N / 1048576
print("→ %.2f MB/s｜1GB 用了 %.0f 秒｜15.99GB 预计 %.0f 分钟"
      % (mb / dt, dt, 15992 / (mb / dt) / 60))

# 清理
import paramiko  # noqa: E402
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nma1.seetacloud.com", port=39522, username="root",
          password="FSMqu7B3fRXc", timeout=30)
_i, o, e = c.exec_command("rm -f /root/autodl-tmp/_slice1g.bin*; echo 已清理", timeout=120)
print(o.read().decode().strip(), e.read().decode().strip())
c.close()
os.remove(SLICE)
