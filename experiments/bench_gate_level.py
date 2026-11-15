# -*- coding: utf-8 -*-
"""基准：pyin 门控提速前后（时间 + 掩码一致度），并验证电平归一的效果。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(ROOT, "tools"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import svc_gate as G  # noqa: E402

VOC = os.path.join(ROOT, "cache", "sing", "produce_20261113-200757",
                   "stems", "vocals.wav")
if not os.path.exists(VOC):
    sys.exit("找不到测试用 vocals：%s" % VOC)
info = sf.info(VOC)
print("测试文件：%s（%.1f 秒 / %d Hz）\n" % (os.path.basename(VOC),
                                          info.duration, info.samplerate))

out = {}
for tag, fast in (("旧(22050/hop256/nthr100)", False), ("新(11025/hop512/nthr48)", True)):
    t0 = time.time()
    m = G.voiced_mask(__import__("pathlib").Path(VOC), info.samplerate,
                      info.frames, fast=fast)
    dt = time.time() - t0
    out[tag] = m
    print("%-28s 耗时 %6.2f 秒｜帧数 %d｜有声占比 %.1f%%"
          % (tag, dt, len(m), 100 * float(np.mean(m > 0.5)) if len(m) else 0))

a, b = list(out.values())
n = min(len(a), len(b))
if n:
    # 按时间重采样到同一长度比较（两边帧率不同）
    idx = (np.arange(n) * (len(a) / n)).astype(int)
    aa = a[idx] > 0.5
    bb = b[:n] > 0.5
    agree = float(np.mean(aa == bb))
    print("\n掩码一致度：%.1f%%（帧率不同，按时间对齐后比较）" % (100 * agree))

print("\n=== 电平归一验证（在副本上试，不动作业）===")
tmp = os.path.join(ROOT, "cache", "sing", "_level_test")
os.makedirs(tmp, exist_ok=True)
for name in ("vocals.wav", "instrumental.wav"):
    src = os.path.join(os.path.dirname(VOC), name)
    if not os.path.exists(src):
        continue
    y, sr = sf.read(src, always_2d=True, dtype="float32")
    sf.write(os.path.join(tmp, name), y, sr, subtype="FLOAT")
import subprocess  # noqa: E402

r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "svc_stage_level.py"),
                    tmp, "--peak-db", "-3"], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print(r.stdout.strip() or r.stderr.strip())
for f in sorted(os.listdir(tmp)):
    y, sr = sf.read(os.path.join(tmp, f), always_2d=True, dtype="float32")
    print("   %-20s 峰值 %+.1f dB｜削波 %d" % (f, 20 * np.log10(max(float(np.max(np.abs(y))), 1e-9)),
                                             int((np.abs(y) >= 0.999).sum())))
