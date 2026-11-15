# -*- coding: utf-8 -*-
"""量指定作业的分轨：电平/削波/相关性/守恒性。

用法：python stem_quality2.py [作业目录名]
"""
from __future__ import annotations

import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
name = sys.argv[1] if len(sys.argv) > 1 else "produce_20261113-200757"
job = os.path.join(ROOT, "cache", "sing", name)
if not os.path.isdir(job):
    sys.exit("没有这个作业目录：%s" % job)

files = sorted(glob.glob(os.path.join(job, "stems", "*.wav")))
print("作业 %s｜%d 个分轨\n" % (name, len(files)))
if not files:
    sys.exit("stems 目录是空的（可能已被清理）")

data = {}
print("%-50s %6s %8s %8s %6s" % ("文件", "秒", "峰值dB", "RMS dB", "削波"))
for f in files:
    try:
        y, sr = sf.read(f, always_2d=True, dtype="float32")
    except Exception as ex:  # noqa: BLE001
        print("  %s 读失败 %s" % (os.path.basename(f), ex))
        continue
    m = y.mean(axis=1)
    pk = float(np.max(np.abs(m))) if len(m) else 1e-9
    rms = float(np.sqrt((m ** 2).mean())) if len(m) else 1e-9
    data[os.path.basename(f)] = m
    print("%-50s %6.1f %8.1f %8.1f %6d"
          % (os.path.basename(f)[:50], len(m) / sr,
             20 * np.log10(max(pk, 1e-9)), 20 * np.log10(max(rms, 1e-9)),
             int((np.abs(m) >= 0.999).sum())))


def corr(a, b):
    n = min(len(a), len(b))
    if n < 1000:
        return float("nan")
    return float(np.corrcoef(a[:n], b[:n])[0, 1])


def find(*keys):
    for k in data:
        if all(x in k.lower() for x in keys):
            return data[k]
    return None


lead = find("lead")
back = find("backing")
voc = find("vocals.wav")
ins = find("instrumental")

print("\n=== 分离质量 ===")
if lead is not None and back is not None:
    print("  lead vs backing 相关性：%.3f   （越低越好，>0.5 说明没分开）"
          % corr(lead, back))
if voc is not None and ins is not None:
    print("  vocals vs instrumental：%.3f  （应≈0）" % corr(voc, ins))
if voc is not None and lead is not None and back is not None:
    n = min(len(voc), len(lead), len(back))
    res = voc[:n] - (lead[:n] + back[:n])
    print("  vocals-(lead+backing) 残差 RMS：%.5f  （越接近 0 说明拆分守恒）"
          % float(np.sqrt((res ** 2).mean())))
