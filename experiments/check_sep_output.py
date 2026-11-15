# -*- coding: utf-8 -*-
"""试听前自检：四轨都有声吗、电平/削波、时长。"""
from __future__ import annotations

import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\音频素材\分离试听\赤蛮奇"
files = sorted(glob.glob(os.path.join(D, "*.wav")))
print("%-26s %7s %8s %8s %7s %9s" % ("文件", "秒", "峰值dB", "RMS dB", "削波", "有声占比"))
for f in files:
    y, sr = sf.read(f, always_2d=True, dtype="float32")
    m = np.abs(y).max(axis=1)
    pk = float(m.max()) if len(m) else 0
    rms = float(np.sqrt((y ** 2).mean())) if y.size else 0
    voiced = float(np.mean(m > 10 ** (-40 / 20))) if len(m) else 0
    print("%-26s %7.1f %8.1f %8.1f %7d %8.1f%%"
          % (os.path.basename(f)[:26], len(y) / sr,
             20 * np.log10(max(pk, 1e-9)), 20 * np.log10(max(rms, 1e-9)),
             int((np.abs(y) >= 0.999).sum()), 100 * voiced))

# 干声在两轨上的相关性：主唱 vs 和声 应该低
def load(n):
    p = os.path.join(D, n)
    if not os.path.exists(p):
        return None
    y, _ = sf.read(p, always_2d=True, dtype="float32")
    return y.mean(axis=1)


lead, back = load("2_干声_主唱.wav"), load("3_干声_和声.wav")
if lead is not None and back is not None:
    n = min(len(lead), len(back))
    print("\n主唱 vs 和声 相关性：%.3f（越低越好）"
          % float(np.corrcoef(lead[:n], back[:n])[0, 1]))
