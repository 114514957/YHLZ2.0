#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并发 HTTP Range 下载（走 SSH direct-tcpip 隧道）。

为什么不用 SFTP：实测 SFTP 单流 0.019 MB/s、HTTP 单流 0.038 MB/s，
SFTP 的逐包确认在慢链路下代价太高。HTTP Range 可以直接要字节区间，
每路独立连接，断了重连即可。

断点续传：每块下完立刻记进 sidecar（.chunks.json），重跑自动跳过。

用法：
    set YH_SSH_PASS=xxx
    python tools/v9_http_pull.py --workers 12
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import paramiko

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RPORT = 18081   # 支持 Range 的自定义服务器（python -m http.server 不支持 Range）
RFILE = "model.safetensors"
LOCAL_DIR = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="connect.nma1.seetacloud.com")
    ap.add_argument("--port", default="39522")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.environ.get("YH_SSH_PASS", ""))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--chunk", type=int, default=1024 * 1024, help="块大小字节（慢链路上必须小：4MB/0.03MBps=133s 会超时）")
    a = ap.parse_args()
    if not a.password:
        print("❌ 需要 YH_SSH_PASS")
        return 2

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=int(a.port), username=a.user, password=a.password,
              timeout=40, banner_timeout=40, auth_timeout=40, look_for_keys=False)

    # 本地转发（多路复用一条 SSH 连接）
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(128)
    lport = srv.getsockname()[1]

    def pipe(x, y):
        try:
            while True:
                d = x.recv(262144)
                if not d:
                    break
                y.sendall(d)
        except Exception:  # noqa: BLE001
            pass
        finally:
            for z in (x, y):
                try:
                    z.shutdown(socket.SHUT_WR)
                except Exception:  # noqa: BLE001
                    pass

    def acceptor():
        while True:
            try:
                cli, peer = srv.accept()
            except OSError:
                return
            try:
                ch = c.get_transport().open_channel(
                    "direct-tcpip", ("127.0.0.1", RPORT), peer)
                threading.Thread(target=pipe, args=(cli, ch), daemon=True).start()
                threading.Thread(target=pipe, args=(ch, cli), daemon=True).start()
            except Exception:  # noqa: BLE001
                cli.close()

    threading.Thread(target=acceptor, daemon=True).start()
    time.sleep(1)
    url = "http://127.0.0.1:%d/%s" % (lport, RFILE)

    # 取文件大小
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        size = int(r.headers.get("Content-Length"))
    print("远端大小：%.2f GB｜块 %d MB｜并发 %d"
          % (size / 1073741824, a.chunk // 1048576, a.workers))

    os.makedirs(LOCAL_DIR, exist_ok=True)
    local = os.path.join(LOCAL_DIR, RFILE)
    side = local + ".chunks.json"
    n = (size + a.chunk - 1) // a.chunk
    done = [False] * n
    if os.path.exists(side):
        try:
            old = json.load(io.open(side, encoding="utf-8"))
            if old.get("size") == size and len(old.get("done", [])) == n:
                done = old["done"]
                print("续传：已完成 %d/%d 块" % (sum(done), n))
        except Exception:  # noqa: BLE001
            pass
    if not os.path.exists(local) or os.path.getsize(local) != size:
        with open(local, "wb") as f:
            f.truncate(size)

    todo = [i for i in range(n) if not done[i]]
    lock = threading.Lock()
    state = {"size": size, "done": done}
    stop = threading.Event()

    def save():
        with lock:
            snap = {"size": size, "done": list(done)}
        tmp = side + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f)
        os.replace(tmp, side)

    def worker():
        while not stop.is_set():
            with lock:
                if not todo:
                    return
                idx = todo.pop()
            lo = idx * a.chunk
            hi = min(lo + a.chunk, size) - 1
            for attempt in range(4):
                try:
                    rq = urllib.request.Request(
                        url, headers={"Range": "bytes=%d-%d" % (lo, hi)})
                    with urllib.request.urlopen(rq, timeout=300) as r:
                        data = r.read()
                    if len(data) != hi - lo + 1:
                        raise IOError("长度不符 %d != %d" % (len(data), hi - lo + 1))
                    with lock:
                        with open(local, "r+b") as f:
                            f.seek(lo)
                            f.write(data)
                        done[idx] = True
                    if idx % 20 == 0:
                        save()
                    break
                except Exception:  # noqa: BLE001
                    if attempt == 3:
                        with lock:
                            todo.append(idx)
                        return
                    time.sleep(2 + attempt * 3)

    t0 = time.time()
    total_chunks = n
    print("开始，共 %d 块待下" % len(todo))
    ths = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in ths:
        t.start()
    last = 0
    try:
        while any(t.is_alive() for t in ths):
            time.sleep(20)
            with lock:
                d = sum(done)
            el = time.time() - t0
            print("[%s] %d/%d 块（%.1f%%）｜%.1f 分钟｜估剩 %.1f 分钟"
                  % (time.strftime("%H:%M:%S"), d, total_chunks,
                     100.0 * d / total_chunks, el / 60,
                     (el / max(1, d - last + 1)) * (total_chunks - d) / 60))
            last = d
            save()
    except KeyboardInterrupt:
        stop.set()
        save()
        print("已中断，状态已保存")
        return 1
    save()
    el = time.time() - t0
    print("\n完成：%.2f GB｜%.1f 分钟｜%.3f MB/s"
          % (os.path.getsize(local) / 1073741824, el / 60,
             os.path.getsize(local) / 1048576 / el))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
