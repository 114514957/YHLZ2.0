# -*- coding: utf-8 -*-
"""给 pyin 找一组「够快且掩码不变」的参数：以旧参数(22050/256/1024/100)为基准比一致度。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import librosa  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
VOC = os.path.join(ROOT, "cache", "sing", "produce_20261113-200757",
                   "stems", "vocals.wav")

CFGS = [
    ("baseline 22050/256/1024/100", 22050, 256, 1024, 100),
    ("D 22050/512/1024/100", 22050, 512, 1024, 100),
    ("B 11025/256/1024/100", 11025, 256, 1024, 100),
    ("C 8000/128/512/100", 8000, 128, 512, 100),
    ("E 11025/256/2048/60", 11025, 256, 2048, 60),
]

t_total = time.time()
base = None
print("%-30s %8s %8s %9s %9s" % ("配置", "耗时s", "有声%", "一致度%", "帧数"))
for tag, sr, hop, flen, nthr in CFGS:
    t0 = time.time()
    y, _ = librosa.load(VOC, sr=sr, mono=True)
    f0, voiced, prob = librosa.pyin(y, fmin=70, fmax=1000, sr=sr,
                                    frame_length=flen, hop_length=hop,
                                    n_thresholds=nthr, fill_na=np.nan)
    m = (voiced & np.isfinite(f0) & (prob > 0.5)).astype(np.uint8)
    dt = time.time() - t0
    ratio = 100 * float(np.mean(m)) if len(m) else 0.0
    if base is None:
        base = m
        agree = 100.0
    else:
        # 按时间对齐（两边帧率不同）
        n = 40000
        ia = (np.arange(n) * (len(base) / n)).astype(int)
        ib = (np.arange(n) * (len(m) / n)).astype(int)
        agree = 100 * float(np.mean(base[ia] == m[ib]))
    print("%-30s %8.1f %8.1f %9.1f %9d" % (tag, dt, ratio, agree, len(m)))

print("\n总耗时 %.1f 秒" % (time.time() - t_total))
