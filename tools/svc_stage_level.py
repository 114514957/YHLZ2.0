# -*- coding: utf-8 -*-
"""分轨电平归一（2026-11-13，老爹「干声分离需要调整」）

实测问题（又三郎那单）：
  vocals.wav        峰值  -0.0 dB  ← 顶满刻度，进 Seed-VC 没余量，容易破音
  instrumental.wav  峰值  +0.8 dB  ← **已经超出满刻度**，10 个样本削顶
  lead/backing      继承了这些电平

Mel-Band-RoFormer 的输出不做增益管理，所以必须由我们**在分离之后、换声之前**
统一归一，给下游留 headroom。

做法：按峰值把每一轨缩到目标值（默认 -3 dBFS ≈ 0.708），只降不升（不放大本来安静的音轨），
写回原文件，并打印原峰值/新峰值，便于追。

用法：
  python tools/svc_stage_level.py <目录或文件>... [--peak-db -3]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--peak-db", type=float, default=-3.0,
                    help="归一目标峰值 dBFS（默认 -3，给 SVC 留余量）")
    ap.add_argument("--allow-boost", action="store_true",
                    help="允许放大（默认只降不升）")
    a = ap.parse_args()

    import numpy as np
    import soundfile as sf

    target = 10 ** (a.peak_db / 20.0)
    files: list[str] = []
    for p in a.paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.wav")))
        elif os.path.isfile(p):
            files.append(p)

    changed = 0
    for f in files:
        try:
            y, sr = sf.read(f, always_2d=True, dtype="float32")
        except Exception as ex:  # noqa: BLE001
            print("  跳过 %s（%s）" % (os.path.basename(f), ex))
            continue
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak <= 1e-9:
            continue
        need = target / peak
        if need >= 1.0 and not a.allow_boost:
            print("  %-44s 峰值 %+5.1f dB｜已有余量，不动"
                  % (os.path.basename(f)[:44], 20 * np.log10(peak)))
            continue
        y = (y * need).astype("float32")
        # 兜底：任何情况下都不许再冒过 0 dBFS
        np.clip(y, -1.0, 1.0, out=y)
        sf.write(f, y, sr, subtype="FLOAT")
        changed += 1
        print("  %-44s %+5.1f dB → %+5.1f dB（×%.3f）"
              % (os.path.basename(f)[:44], 20 * np.log10(peak),
                 20 * np.log10(float(np.max(np.abs(y)))), need))
    print("归一完成：处理 %d 个文件（目标 %+.1f dBFS）" % (changed, a.peak_db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
