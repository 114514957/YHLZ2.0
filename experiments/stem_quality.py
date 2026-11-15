# -*- coding: utf-8 -*-
"""量干声质量：电平 / 削波 / 主唱与和声的相关性 / 门控前后差异。"""
from __future__ import annotations

import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
JOB = sorted(glob.glob(os.path.join(ROOT, "cache", "sing", "produce_*")),
             key=lambda p: -os.path.getmtime(p))[0]
print("作业：%s\n" % os.path.basename(JOB))


def load(p):
    y, sr = sf.read(p, always_2d=True, dtype="float32")
    return y.mean(axis=1), sr


def info(p):
    y, sr = load(p)
    peak = float(np.max(np.abs(y)) or 1e-9)
    rms = float(np.sqrt(np.mean(y ** 2)) or 1e-9)
    clip = int(np.sum(np.abs(y) >= 0.999))
    return {"name": os.path.basename(p), "sr": sr, "dur": len(y) / sr,
            "peak_db": round(20 * np.log10(peak), 1),
            "rms_db": round(20 * np.log10(rms), 1),
            "clip": clip, "y": y}


rows = []
for f in sorted(glob.glob(os.path.join(JOB, "stems", "*.wav")) +
                glob.glob(os.path.join(JOB, "*.wav"))):
    try:
        rows.append(info(f))
    except Exception as ex:  # noqa: BLE001
        print("  读不了 %s：%s" % (os.path.basename(f), ex))

print("%-46s %5s %7s %8s %8s %6s" % ("文件", "秒", "峰值dB", "RMS dB", "削波", "sr"))
for r in rows:
    print("%-46s %5.1f %7.1f %8.1f %8d %6d"
          % (r["name"][:46], r["dur"], r["peak_db"], r["rms_db"], r["clip"], r["sr"]))

# 主唱 vs 和声相关性（同一长度段）
def corr(a, b):
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    return float(np.corrcoef(a, b)[0, 1])


d = {r["name"]: r for r in rows}
lead = next((r for k, r in d.items() if "lead" in k.lower()), None)
back = next((r for k, r in d.items() if "backing" in k.lower()), None)
voc = next((r for k, r in d.items() if k.startswith("vocals.wav")), None)
ins = next((r for k, r in d.items() if "instrumental" in k.lower()), None)

print("\n=== 相关性（越高越说明没分开）===")
if lead and back:
    print("  lead vs backing : %.3f   ← 应该很低（<0.3）" % corr(lead["y"], back["y"]))
if voc and lead and back:
    n = min(len(voc["y"]), len(lead["y"]))
    res = voc["y"][:n] - (lead["y"][:n] + back["y"][:n])
    print("  vocals - (lead+backing) 残差 RMS：%.5f（越接近 0 说明拆分守恒）"
          % float(np.sqrt(np.mean(res ** 2))))
if voc and ins:
    print("  vocals vs instrumental: %.3f  ← 应该接近 0（人声与伴奏不该相似）"
          % corr(voc["y"], ins["y"]))
