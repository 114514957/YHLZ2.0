#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拉 V9 重训产物（复用 .tmp/autopull.py 的多流断点续传）。

为什么不用 sftp.get：上次实测单流仅 0.12–0.15 MB/s，7.5 GB 要 16 小时；
而且 `prefetch(整文件)` 会让远端直接断连（实测 10054）。
autopull 的方案是 8 MB 分块 + 工作队列多流 + sidecar 记录已完成块，断了能续。
"""
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 载入 autopull 模块
spec = importlib.util.spec_from_file_location(
    "autopull", os.path.join(ROOT, ".tmp", "autopull.py"))
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

# 改指向本次产物
ap.OUT = "/root/autodl-tmp/models/full/qwen3-4b-yuanheng-v9t"
ap.LOCAL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
ap.TRAINLOG = "/root/autodl-tmp/logs/train_v9t.log"
os.makedirs(ap.LOCAL, exist_ok=True)

STREAMS = int(os.environ.get("YH_STREAMS", "6"))
BIG = "model.safetensors"
remote = ap.OUT + "/" + BIG
local = os.path.join(ap.LOCAL, BIG)

print("=" * 66)
print("拉取 %s" % BIG)
print("  远端：%s" % remote)
print("  本地：%s" % local)
print("  流数：%d｜块大小：%d MB" % (STREAMS, ap.CHUNK // 1048576))
print("=" * 66)

t0 = time.time()
last = {"t": t0, "n": 0}


def progress():
    """每 30 秒报一次进度。"""
    while True:
        time.sleep(30)
        try:
            got = os.path.getsize(local) if os.path.exists(local) else 0
            side = local + ".chunks.json"
            done = 0
            total = 1
            if os.path.exists(side):
                import json
                st = json.loads(open(side).read())
                done = sum(1 for x in st["done"] if x)
                total = len(st["done"])
            el = time.time() - t0
            print("[%s] %d/%d 块（%.1f%%）｜已传 %.2f GB｜%.1f 分钟"
                  % (time.strftime("%H:%M:%S"), done, total,
                     100.0 * done / max(1, total), got / 1073741824, el / 60),
                  flush=True)
        except Exception:  # noqa: BLE001
            pass


import threading  # noqa: E402

threading.Thread(target=progress, daemon=True).start()

ap.download_multi(remote, local, streams=STREAMS)

t = time.time() - t0
sz = os.path.getsize(local)
print("\n✅ 下载完成：%.2f GB｜%.1f 分钟｜平均 %.2f MB/s"
      % (sz / 1073741824, t / 60, sz / 1048576 / t))

# md5 校验
print("\n校验 md5 …")
m_local = ap.md5_local(local)
m_remote = ap.md5_remote(remote)
print("  本地 %s" % m_local)
print("  远端 %s" % m_remote)
print("  %s" % ("✅ 一致" if m_local == m_remote else "❌ 不一致"))
