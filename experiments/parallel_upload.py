# -*- coding: utf-8 -*-
"""多连接并行上传大文件（单连接只有 0.2MB/s，必须多路）。

用法：python parallel_upload.py <本地文件> <远端路径> [路数]
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"


def conn():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)
    return c


class RangeReader:
    """把本地文件的某个区间伪装成文件对象，供 sftp.putfo 读取。"""

    def __init__(self, path, start, length):
        self.f = open(path, "rb")
        self.f.seek(start)
        self.left = length

    def read(self, n=-1):
        if self.left <= 0:
            return b""
        if n is None or n < 0:
            n = self.left
        n = min(n, self.left)
        data = self.f.read(n)
        self.left -= len(data)
        return data

    def close(self):
        self.f.close()


def main() -> int:
    local, remote = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    size = os.path.getsize(local)
    step = size // n
    ranges = []
    for i in range(n):
        s = i * step
        e = size - 1 if i == n - 1 else s + step - 1
        ranges.append((i, s, e))

    print("上传 %s（%.2f GB）→ %s，%d 路" % (local, size / 1e9, remote, n))
    done = [0] * n
    errs = {}

    def work(i, s, e):
        want = e - s + 1
        rp = "%s.part%d" % (remote, i)
        for attempt in range(1, 31):
            have = 0
            try:
                c = conn()
                sftp = c.open_sftp()
                try:
                    have = sftp.stat(rp).st_size
                except IOError:
                    have = 0
                if have >= want:
                    done[i] = have
                    sftp.close()
                    c.close()
                    return
                rr = RangeReader(local, s + have, want - have)
                mode = "ab" if have else "wb"
                rf = sftp.open(rp, mode)
                sftp.get_channel().settimeout(120)
                chunk = 1 << 20
                sent = have
                while sent < want:
                    data = rr.read(chunk)
                    if not data:
                        break
                    rf.write(data)
                    sent += len(data)
                    done[i] = sent
                rf.close()
                rr.close()
                sftp.close()
                c.close()
                done[i] = sent
                if sent >= want:
                    return
            except Exception as ex:  # noqa: BLE001
                errs[i] = type(ex).__name__
                done[i] = have if have else done[i]
                time.sleep(3)
        raise RuntimeError("第 %d 段 30 次没传完" % i)

    ths = [threading.Thread(target=work, args=r, daemon=True) for r in ranges]
    t0 = time.time()
    for t in ths:
        t.start()
    last = -1
    while any(t.is_alive() for t in ths):
        time.sleep(15)
        tot = sum(done)
        if tot != last:
            el = time.time() - t0
            print("  %.1f%%  %.2f/%.2f GB  %.2f MB/s  (%.0fs)"
                  % (100 * tot / size, tot / 1e9, size / 1e9,
                     tot / 1048576 / max(1, el), el), flush=True)
            last = tot
    for t in ths:
        t.join()
    if errs:
        print("  期间重试：%s" % errs)

    print("拼装（云端）…")
    c = conn()
    _i, o, e = c.exec_command(
        "cd $(dirname %s) && cat %s.part* > %s && rm -f %s.part* && stat -c %%s %s"
        % (remote, remote, remote, remote, remote), timeout=1800)
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    c.close()
    print("云端大小：%s（应 %d）｜%s" % (out, size, err))
    return 0 if out.isdigit() and int(out) == size else 3


if __name__ == "__main__":
    raise SystemExit(main())
