# -*- coding: utf-8 -*-
"""多连接分块下载：链路单连接只有 ~50KB/s，改成 N 路并行 + 每块断点续传 + 末尾校验。

用法：
    python chunk_fetch.py v9t10            # 下 adapter_model.safetensors
    python chunk_fetch.py v9t10 --chunks 8

原理：远端文件按 byte range 切成 N 块，每块单独一条 SFTP 连接、
从本地对应 .part 文件的长度处接着读；全部齐了拼成一个文件，比对 sha256。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER = "connect.nma1.seetacloud.com", 39522, "root"
PW = os.environ.get("YH_SSH_PASS", "")
LOCAL_ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\lora"


def sha256(p, block=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(block), b""):
            h.update(c)
    return h.hexdigest()


def connect():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)
    return c


def remote_info(path):
    """返回 (size, sha256)"""
    c = connect()
    _i, o, _e = c.exec_command("stat -c %%s %s; sha256sum %s | cut -d' ' -f1" % (path, path),
                              timeout=300)
    txt = o.read().decode().split()
    c.close()
    return int(txt[0]), txt[1]


def fetch_chunk(rpath, out, start, end, label):
    """下载 [start, end] 区间到 out 文件（续传）"""
    want = end - start + 1
    for attempt in range(1, 41):
        have = os.path.getsize(out) if os.path.exists(out) else 0
        if have >= want:
            return True
        try:
            c = connect()
            s = c.open_sftp()
            rf = s.open(rpath, "rb")
            rf.seek(start + have)
            remain = want - have
            with open(out, "ab") as f:
                while remain > 0:
                    chunk = rf.read(min(1 << 20, remain))
                    if not chunk:
                        break
                    f.write(chunk)
                    remain -= len(chunk)
            rf.close()
            s.close()
            c.close()
        except Exception as ex:  # noqa: BLE001
            got = os.path.getsize(out) if os.path.exists(out) else 0
            print("  [%s 重试%2d] %d/%d（%s）" % (label, attempt, got, want,
                                                type(ex).__name__), flush=True)
            time.sleep(3)
    return (os.path.getsize(out) if os.path.exists(out) else 0) >= want


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", default="v9t10", nargs="?")
    ap.add_argument("--chunks", type=int, default=6)
    ap.add_argument("--file", default="adapter_model.safetensors")
    a = ap.parse_args()

    if not PW:
        sys.exit("需要 YH_SSH_PASS")

    rpath = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-%s/%s" % (a.tag, a.file)
    size, rsha = remote_info(rpath)
    print("远端 %s：%d 字节｜sha256 %s" % (a.file, size, rsha[:16]))

    ldir = os.path.join(LOCAL_ROOT, "yuanheng-v9-gemma-%s" % a.tag)
    os.makedirs(ldir, exist_ok=True)
    final = os.path.join(ldir, a.file)

    # 已经完整就不再下
    if os.path.exists(final) and os.path.getsize(final) == size and sha256(final) == rsha:
        print("✅ 本地已完整且 sha256 一致，跳过")
        return 0

    n = max(1, a.chunks)
    step = size // n
    ranges = []
    for i in range(n):
        s0 = i * step
        s1 = (size - 1) if i == n - 1 else (s0 + step - 1)
        ranges.append((s0, s1))
    print("切成 %d 块，并行下载中…" % n, flush=True)

    import threading
    results = {}

    def work(i, s0, s1):
        out = os.path.join(ldir, ".%s.part%d" % (a.file, i))
        results[i] = fetch_chunk(rpath, out, s0, s1, "p%d" % i)

    t0 = time.time()
    ths = [threading.Thread(target=work, args=(i, s0, s1)) for i, (s0, s1) in enumerate(ranges)]
    for t in ths:
        t.start()
    last = -1
    while any(t.is_alive() for t in ths):
        time.sleep(15)
        got = sum(os.path.getsize(os.path.join(ldir, ".%s.part%d" % (a.file, i)))
                  for i in range(n) if os.path.exists(os.path.join(ldir, ".%s.part%d" % (a.file, i))))
        print("   %5.1f%%  %d/%d  (%.0fs)" % (100 * got / size, got, size, time.time() - t0),
              flush=True)
    for t in ths:
        t.join()

    if not all(results.values()):
        print("❌ 有块没下完：%s" % {k: v for k, v in results.items() if not v})
        return 3

    print("拼装…")
    with open(final, "wb") as f:
        for i in range(n):
            p = os.path.join(ldir, ".%s.part%d" % (a.file, i))
            with open(p, "rb") as g:
                for c in iter(lambda: g.read(1 << 20), b""):
                    f.write(c)
            os.remove(p)

    got_sha = sha256(final)
    ok = got_sha == rsha
    print("本地 %d 字节｜sha256 %s｜%s" % (os.path.getsize(final), got_sha[:16],
                                       "✅ 与远端一致" if ok else "❌ 不一致"))
    print("耗时 %.0f 秒" % (time.time() - t0))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
