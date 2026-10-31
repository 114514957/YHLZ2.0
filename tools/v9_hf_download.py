#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直连下载 HF 文件（绕开 httpx 与畸形 NO_PROXY）。

背景：本机 NO_PROXY 含畸形项 `[::1]`，httpx 解析成 `Invalid port: ':1]'`
（台账 0815 记录过同类问题）；huggingface_hub 全程用 httpx，因此直接失败。
本脚本用 urllib + **显式空 ProxyHandler**（不走任何代理），并对 hf-mirror 直连。

用法：
    python tools/v9_hf_download.py --repo unsloth/Qwen3.5-4B-GGUF \
        --file Qwen3.5-4B-Q4_K_M.gguf --dest models\\qwen35-4b
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

MIRROR = "https://hf-mirror.com"


def download(repo: str, filename: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, os.path.basename(filename))
    url = "%s/%s/resolve/main/%s" % (MIRROR, repo, filename)

    # 关键：显式空 ProxyHandler，避免读 NO_PROXY（含畸形 [::1]）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "yhlz-downloader/1.0")]

    tmp = out + ".part"
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    req = urllib.request.Request(url)
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    t0 = time.time()
    with opener.open(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0) + have
        mode = "ab" if have and r.status == 206 else "wb"
        if mode == "wb":
            have = 0
        print("下载 %s -> %.2f GB%s" % (filename, total / 2**30,
                                        "（续传）" if mode == "ab" else ""), flush=True)
        done = have
        last = 0.0
        with open(tmp, mode) as fh:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 2:
                    last = now
                    sp = done / max(now - t0, 1e-6) / 2**20
                    pct = 100.0 * done / total if total else 0
                    print("  %5.1f%%  %6.0f/%0.f MB  %.1f MB/s"
                          % (pct, done / 2**20, total / 2**20, sp), flush=True)
    os.replace(tmp, out)
    print("完成 %s（%.1fs）" % (out, time.time() - t0), flush=True)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--dest", required=True)
    a = ap.parse_args()
    download(a.repo, a.file, a.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
