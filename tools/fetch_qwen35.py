#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 ModelScope 并发下载 Qwen3.5-4B 原始权重（safetensors 格式）。

为什么不从 HF 下：本机到 huggingface.co 不通（实测 443 不可达）；
ModelScope 单流 8 MB/s，Range 可用（206），多路分块能更快。

为什么下 3.5 而不是 Qwen3-4B：老爹指定要 3.5，用于 neuron-explorer 那套
（它的预计算缓存是给 Qwen3.5-4B 的）。

用法：
    python tools/fetch_qwen35.py
    python tools/fetch_qwen35.py --workers 8
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "Qwen/Qwen3.5-4B"
BASE = "https://www.modelscope.cn/models/%s/resolve/master/" % REPO
DEST = os.path.join(ROOT, "models", "qwen35-4b-hf")
UA = {"User-Agent": "Mozilla/5.0"}

BIG = ["model.safetensors-00001-of-00002.safetensors",
       "model.safetensors-00002-of-00002.safetensors"]
SMALL = ["config.json", "model.safetensors.index.json", "tokenizer.json",
         "tokenizer_config.json", "generation_config.json",
         "chat_template.jinja", "merges.txt", "vocab.json"]


def head_size(name: str) -> int:
    """ModelScope 的 HEAD 不给 Content-Length，用 Range 请求从 Content-Range 里取总大小。"""
    req = urllib.request.Request(
        BASE + name, headers={**UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        cr = r.headers.get("Content-Range") or ""
        r.read()
    if "/" in cr:
        return int(cr.rsplit("/", 1)[1])
    # 兜底：不带 Range 读头
    req2 = urllib.request.Request(BASE + name, headers=UA)
    with urllib.request.urlopen(req2, timeout=30) as r2:
        return int(r2.headers["Content-Length"])


def get_small(name: str) -> None:
    dst = os.path.join(DEST, name)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    req = urllib.request.Request(BASE + name, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
            f.write(r.read())
        print("  ✅ %-42s %8.1f KB" % (name, os.path.getsize(dst) / 1024))
    except Exception as e:  # noqa: BLE001
        if os.path.exists(dst):
            os.remove(dst)
        print("  ⚠ %-42s 跳过（%s）" % (name, str(e)[:40]))


def get_big(name: str, workers: int, chunk: int) -> None:
    url = BASE + name
    dst = os.path.join(DEST, name)
    side = dst + ".chunks.json"
    size = head_size(name)
    n = (size + chunk - 1) // chunk
    done = [False] * n
    if os.path.exists(side):
        try:
            old = json.load(io.open(side, encoding="utf-8"))
            if old.get("size") == size and len(old.get("done", [])) == n:
                done = old["done"]
                if any(done):
                    print("  续传：已完成 %d/%d 块" % (sum(done), n))
        except Exception:  # noqa: BLE001
            pass
    if not os.path.exists(dst) or os.path.getsize(dst) != size:
        with open(dst, "wb") as f:
            f.truncate(size)
    todo = [i for i in range(n) if not done[i]]
    lock = threading.Lock()
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
            lo = idx * chunk
            hi = min(lo + chunk, size) - 1
            for attempt in range(4):
                try:
                    req = urllib.request.Request(
                        url, headers={**UA, "Range": "bytes=%d-%d" % (lo, hi)})
                    with urllib.request.urlopen(req, timeout=180) as r:
                        data = r.read()
                    if len(data) != hi - lo + 1:
                        raise IOError("长度不符 %d != %d"
                                      % (len(data), hi - lo + 1))
                    with lock:
                        with open(dst, "r+b") as f:
                            f.seek(lo)
                            f.write(data)
                        done[idx] = True
                    break
                except Exception:  # noqa: BLE001
                    if attempt == 3:
                        with lock:
                            todo.append(idx)
                        return
                    time.sleep(1 + attempt * 2)

    t0 = time.time()
    print("  文件 %.2f GB｜%d 块（%d MB）｜%d 路｜待下 %d 块"
          % (size / 1073741824, n, chunk // 1048576, workers, len(todo)))
    ths = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in ths:
        t.start()
    last = 0
    while any(t.is_alive() for t in ths):
        time.sleep(5)
        with lock:
            d = sum(done)
        if d - last >= max(8, n // 40):
            el = time.time() - t0
            spd = (d * chunk) / 1048576 / el if el else 0
            print("    %d/%d 块（%.0f%%）｜%.1f MB/s｜剩 %.1f 分钟"
                  % (d, n, 100.0 * d / n, spd,
                     (n - d) * chunk / 1048576 / max(0.1, spd) / 60))
            last = d
    save()
    el = time.time() - t0
    got = os.path.getsize(dst)
    print("  ✅ %-42s %.2f GB｜%.1f 分钟｜%.1f MB/s%s"
          % (name, got / 1073741824, el / 60,
             got / 1048576 / el if el else 0,
             "" if got == size else " ❌ 大小不符"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--chunk-mb", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(DEST, exist_ok=True)
    print("目标：%s\n" % DEST)

    print("① 小文件")
    for n in SMALL:
        get_small(n)

    print("\n② 大文件（safetensors）")
    for n in BIG:
        p = os.path.join(DEST, n)
        side = p + ".chunks.json"
        if os.path.exists(p) and os.path.exists(side):
            try:
                st = json.load(io.open(side, encoding="utf-8"))
                if all(st.get("done", [])):
                    print("  ✅ %-42s 已完成，跳过" % n)
                    continue
            except Exception:  # noqa: BLE001
                pass
        print("  ↓ %s" % n)
        get_big(n, a.workers, a.chunk_mb * 1048576)

    # 收尾
    print("\n③ 结果")
    tot = 0
    for f in sorted(os.listdir(DEST)):
        if f.endswith(".chunks.json"):
            continue
        p = os.path.join(DEST, f)
        sz = os.path.getsize(p)
        tot += sz
        print("  %-50s %8.2f MB" % (f, sz / 1048576))
    print("  ─────────────────────────────────────────────────────")
    print("  合计 %.2f GB" % (tot / 1073741824))
    return 0


if __name__ == "__main__":
    sys.exit(main())
