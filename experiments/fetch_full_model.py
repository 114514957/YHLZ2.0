# -*- coding: utf-8 -*-
"""下载全量微调产物（12 路并行 + 断点续传）。"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
REMOTE = "/root/autodl-tmp/models/full/yuanheng-v9f1-gemma"
LOCAL = os.path.join(YH, "models", "full", "yuanheng-v9f1-gemma")
BIG = "model.safetensors"
SMALL = ["config.json", "generation_config.json", "tokenizer.json",
         "tokenizer_config.json", "chat_template.jinja",
         "train_summary.json", "train_summary.md", "train_log.csv"]
N = 12

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)
    return c


os.makedirs(LOCAL, exist_ok=True)

c0 = conn()
s0 = c0.open_sftp()
size = s0.stat(REMOTE + "/" + BIG).st_size
for f in SMALL:
    try:
        s0.get(REMOTE + "/" + f, os.path.join(LOCAL, f))
    except IOError:
        pass
s0.close()
c0.close()
print("小文件已拿｜大文件 %d 字节（%.2f GB）" % (size, size / 1e9))

final = os.path.join(LOCAL, BIG)
step = size // N
done = [0] * N


def work(i):
    start = i * step
    end = size - 1 if i == N - 1 else (i + 1) * step - 1
    want = end - start + 1
    part = final + ".p%02d" % i
    for _try in range(30):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have >= want:
            done[i] = have
            return
        try:
            c = conn()
            s = c.open_sftp()
            rf = s.open(REMOTE + "/" + BIG, "rb")
            rf.seek(start + have)
            with open(part, "ab") as f:
                left = want - have
                while left > 0:
                    b = rf.read(min(4 << 20, left))
                    if not b:
                        break
                    f.write(b)
                    left -= len(b)
                    done[i] = want - left
            rf.close()
            s.close()
            c.close()
        except Exception as ex:  # noqa: BLE001
            print("  [p%02d 重试] %s" % (i, type(ex).__name__), flush=True)
            time.sleep(3)
    done[i] = os.path.getsize(part) if os.path.exists(part) else 0


ths = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(N)]
t0 = time.time()
for t in ths:
    t.start()
last = -1
while any(t.is_alive() for t in ths):
    time.sleep(60)
    tot = sum(done)
    mb = tot / 1048576 / max(1, time.time() - t0)
    if tot != last:
        print("  %5.1f%%  %.2f/%.2f GB  %.2f MB/s  剩 %.0f 分钟"
              % (100 * tot / size, tot / 1e9, size / 1e9, mb,
                 (size - tot) / 1048576 / max(mb, 0.1) / 60), flush=True)
        last = tot
for t in ths:
    t.join()

print("拼装…")
with open(final, "wb") as out:
    for i in range(N):
        p = final + ".p%02d" % i
        with open(p, "rb") as g:
            for chunk in iter(lambda: g.read(8 << 20), b""):
                out.write(chunk)
        os.remove(p)
ok = os.path.getsize(final) == size
print("完成 %d 字节 %s｜总耗时 %.0f 分钟"
      % (os.path.getsize(final), "OK" if ok else "BAD", (time.time() - t0) / 60))
