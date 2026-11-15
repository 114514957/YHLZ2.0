# -*- coding: utf-8 -*-
"""新链路这单的验收：阶段耗时、电平、削波、成品信息。"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
jobs = sorted(glob.glob(os.path.join(ROOT, "cache", "sing", "produce_*")),
              key=lambda p: -os.path.getmtime(p))
job = jobs[0]
print("最新作业：%s\n" % os.path.basename(job))

log = os.path.join(job, "release.log")
if os.path.exists(log):
    stages = []
    for ln in open(log, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln.startswith("{") and '"stage"' in ln:
            try:
                stages.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                pass
    print("阶段耗时（从流式日志读的）：")
    total = 0.0
    for s in stages:
        e = float(s.get("elapsed_s") or 0)
        total += e
        print("   %-8s %6.1f 秒" % (s.get("stage"), e))
    print("   %-8s %6.1f 秒（各阶段合计）" % ("合计", total))

print("\n分轨电平：")
for f in sorted(glob.glob(os.path.join(job, "stems", "*.wav"))):
    y, sr = sf.read(f, always_2d=True, dtype="float32")
    m = y.mean(axis=1)
    pk = float(np.max(np.abs(m))) if len(m) else 0
    print("   %-44s %+6.1f dB｜削波 %d"
          % (os.path.basename(f)[:44], 20 * np.log10(max(pk, 1e-9)),
             int((np.abs(m) >= 0.999).sum())))

print("\n成品：")
outs = glob.glob(os.path.join(ROOT, "音频素材", "翻唱产出", "*黑夜梦想家*", "*.wav"))
outs.sort(key=lambda p: -os.path.getmtime(p))
for f in outs[:2]:
    y, sr = sf.read(f, always_2d=True, dtype="float32")
    m = y.mean(axis=1)
    pk = float(np.max(np.abs(m)))
    print("   %-46s %.1f 秒｜%+5.1f dB｜削波 %d"
          % (os.path.basename(f)[:46], len(m) / sr, 20 * np.log10(max(pk, 1e-9)),
             int((np.abs(m) >= 0.999).sum())))
