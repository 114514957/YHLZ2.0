#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""等显存够了再启动 V9 QLoRA 训练（不抢占常驻 llama-server，也不跟语音训练抢）。

背景（2026-10-20）：
  · GPU 只 8 GB；常驻生产 gemma（llama-server，~2.5-3 GB）+ GPT-SoVITS 语音训练（~2-3 GB）
    同时占着，裸启动 QLoRA 必 OOM。
  · V9 配置 seq_len=768（实测 p99=679、max=765，零截断）→ 需求约 3.6 GB。
  · 本脚本轮询显存，等 free ≥ 阈值（默认 4200 MiB）再 exec 训练；
    超时则放弃并把原因写进日志（不硬上）。

用法：
    python tools/v9_train_when_free.py --min-free 4200 --timeout 3600
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "cache" / "v9_train_run.log"


def gpu_free_mib() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20).stdout
        vals = [int(re.findall(r"\d+", x)[0]) for x in out.splitlines() if re.findall(r"\d+", x)]
        return min(vals) if vals else -1
    except Exception:
        return -1


def log(msg: str) -> None:
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-free", type=int, default=4200)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--poll", type=int, default=20)
    a = ap.parse_args()

    log("等待显存：需要 free ≥ %d MiB，最多等 %d 秒" % (a.min_free, a.timeout))
    t0 = time.time()
    while True:
        free = gpu_free_mib()
        log("当前 free = %s MiB" % free)
        if free >= a.min_free:
            break
        if time.time() - t0 > a.timeout:
            log("超时放弃：%d 秒内 free 一直 < %d MiB，不硬上（会 OOM）" % (a.timeout, a.min_free))
            return 2
        time.sleep(a.poll)

    cmd = [sys.executable, "-u", str(ROOT / "tools" / "finetune_train.py"),
           "--config", str(ROOT / "config" / "finetune_v9.json")]
    log("显存就绪，启动训练：" + " ".join(cmd[1:]))
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    p = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip()
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    rc = p.wait()
    log("训练进程结束，退出码 %d" % rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
