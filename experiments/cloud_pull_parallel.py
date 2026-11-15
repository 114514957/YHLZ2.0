# -*- coding: utf-8 -*-
"""并行分块下载 adapter（单流只有 ~0.01MB/s，133MB 要 3 小时）。

做法：云端先 `split` 成 8MB 小块（已有就不用重切），本地用 8 个连接并发拉，
再按序拼接 + 校验 sha256。
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
REMOTE = "/root/autodl-tmp/models/lora/yuanheng-v13/adapter_model.safetensors"
RDIR = "/root/yh/v13_chunks"
LOCAL_DIR = os.path.join(ROOT, "cache", "v13_chunks")
LOCAL_FILE = os.path.join(ROOT, "models", "lora", "yuanheng-v13", "adapter_model.safetensors")
HOST, PORT, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
CHUNK = 8 * 1024 * 1024
WORKERS = 8


def conn() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PWD, timeout=40)
    return c


cli = conn()


def sh(cmd: str, timeout: int = 300) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


# 1) 云端切块（幂等）
print(sh("set -e; mkdir -p %s; rm -f %s/part_*; "
         "split -b %d -d -a 3 %s %s/part_; ls %s | wc -l; du -sh %s"
         % (RDIR, RDIR, CHUNK, REMOTE, RDIR, RDIR, RDIR)))

parts = [ln.strip() for ln in
         sh("ls %s | sort" % RDIR).splitlines() if ln.strip().startswith("part_")]
print("云端块数：%d" % len(parts))
os.makedirs(LOCAL_DIR, exist_ok=True)


def fetch(name: str) -> tuple[str, int, float]:
    lp = os.path.join(LOCAL_DIR, name)
    if os.path.exists(lp) and os.path.getsize(lp) > 0:
        return name, os.path.getsize(lp), 0.0
    t0 = time.time()
    c = conn()
    try:
        sf = c.open_sftp()
        sf.get("%s/%s" % (RDIR, name), lp)
        sf.close()
    finally:
        c.close()
    return name, os.path.getsize(lp), time.time() - t0


t_start = time.time()
done = 0
with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for name, size, dt in ex.map(fetch, parts):
        done += 1
        print("  [%2d/%2d] %-10s %6.1f MB%s"
              % (done, len(parts), name, size / 1048576,
                 ("  %.1f 秒" % dt) if dt else "  （已存在）"), flush=True)

# 2) 拼接
h = hashlib.sha256()
os.makedirs(os.path.dirname(LOCAL_FILE), exist_ok=True)
with open(LOCAL_FILE, "wb") as out:
    for name in parts:
        with open(os.path.join(LOCAL_DIR, name), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                out.write(chunk)
                h.update(chunk)
local_size = os.path.getsize(LOCAL_FILE)
remote_sha = sh("sha256sum %s | cut -d' ' -f1" % REMOTE).strip()
print("\n拼接完成：%.1f MB｜用时 %.1f 分钟"
      % (local_size / 1048576, (time.time() - t_start) / 60))
print("本地 sha256：%s" % h.hexdigest())
print("云端 sha256：%s" % remote_sha)
print("校验：%s" % ("✅ 一致" if h.hexdigest() == remote_sha else "❌ 不一致"))
cli.close()
