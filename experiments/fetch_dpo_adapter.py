# -*- coding: utf-8 -*-
"""Fetch a DPO adapter from the cloud (parallel chunks + resume).

Usage: python fetch_dpo_adapter.py [tag]
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAG = sys.argv[1] if len(sys.argv) > 1 else "v9t10-dpo2"
REMOTE = "/root/autodl-tmp/models/lora/yuanheng-" + TAG
LOCAL = os.path.join(YH, "models", "lora", "yuanheng-" + TAG)
FILES = ["adapter_model.safetensors", "adapter_config.json", "README.md",
         "chat_template.jinja", "_dpo_meta.json"]
N = 6

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)
    return c


os.makedirs(LOCAL, exist_ok=True)


def fetch_file(name):
    c0 = conn()
    s0 = c0.open_sftp()
    try:
        size = s0.stat(REMOTE + "/" + name).st_size
    except IOError:
        print("  skip (not on remote): %s" % name)
        s0.close()
        c0.close()
        return
    s0.close()
    c0.close()
    final = os.path.join(LOCAL, name)
    if size < 4 << 20:
        c = conn()
        s = c.open_sftp()
        s.get(REMOTE + "/" + name, final)
        s.close()
        c.close()
        print("  %-28s %d bytes" % (name, os.path.getsize(final)))
        return
    step = size // N
    done = [0] * N

    def work(i, start, end):
        want = end - start + 1
        part = final + ".p%d" % i
        for _try in range(20):
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if have >= want:
                done[i] = have
                return
            try:
                c = conn()
                s = c.open_sftp()
                rf = s.open(REMOTE + "/" + name, "rb")
                rf.seek(start + have)
                with open(part, "ab") as f:
                    left = want - have
                    while left > 0:
                        b = rf.read(min(1 << 20, left))
                        if not b:
                            break
                        f.write(b)
                        left -= len(b)
                        done[i] = want - left
                rf.close()
                s.close()
                c.close()
            except Exception as ex:  # noqa: BLE001
                print("    [p%d retry] %s" % (i, type(ex).__name__), flush=True)
                time.sleep(2)
        done[i] = os.path.getsize(part) if os.path.exists(part) else 0

    ths = [threading.Thread(
        target=work,
        args=(i, i * step, size - 1 if i == N - 1 else (i + 1) * step - 1),
        daemon=True) for i in range(N)]
    t0 = time.time()
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        time.sleep(20)
        tot = sum(done)
        print("  %-28s %5.1f%%" % (name, 100 * tot / size), flush=True)
    for t in ths:
        t.join()
    with open(final, "wb") as out:
        for i in range(N):
            with open(final + ".p%d" % i, "rb") as g:
                for chunk in iter(lambda: g.read(1 << 20), b""):
                    out.write(chunk)
            os.remove(final + ".p%d" % i)
    ok = os.path.getsize(final) == size
    print("  %-28s %d bytes (%.0f s) %s"
          % (name, os.path.getsize(final), time.time() - t0, "OK" if ok else "BAD"))


for f in FILES:
    fetch_file(f)
print("\nLOCAL %s:" % LOCAL)
for f in sorted(os.listdir(LOCAL)):
    print("   %-30s %d" % (f, os.path.getsize(os.path.join(LOCAL, f))))
