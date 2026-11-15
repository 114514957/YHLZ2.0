# -*- coding: utf-8 -*-
"""量去混响效果：音符收尾后的"尾巴"能量掉了多少（越少越干）。

做法：找能量骤降的帧（收尾），比较之后 50–300ms 内的残余能量占收尾前能量的比例。
混响重 → 尾巴占比高；去混响后应明显下降。
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

D = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\音频素材\分离试听\赤蛮奇"
PAIRS = [("1_干声_主唱+和声.wav", "原始干声"),
         ("7_干声_去混响+谱减.wav", "去混响+谱减"),
         ("6_干声_预处理后.wav", "只谱减(v1)")]

SR = 44100
HOP = 4410          # 100ms
TAIL = int(0.30 * SR)


def tail_ratio(path: str) -> tuple[float, float, float]:
    y, sr = sf.read(path, always_2d=True, dtype="float32")
    m = np.abs(y).mean(axis=1)
    # 每 100ms 的 RMS 包络
    n = len(m) // HOP
    env = np.array([float(np.sqrt((m[i * HOP:(i + 1) * HOP] ** 2).mean()))
                    for i in range(n)])
    if env.max() <= 0:
        return 0.0, 0.0, 0.0
    env_n = env / env.max()
    ratios = []
    for i in range(2, n - 4):
        # 骤降：前 100ms 有能量，后 100ms 掉到 40% 以下
        if env_n[i] > 0.25 and env_n[i + 1] < 0.4 * env_n[i]:
            start = (i + 1) * HOP
            seg = m[start:start + TAIL]
            if len(seg) < TAIL // 2:
                continue
            before = float(np.sqrt((m[i * HOP:(i + 1) * HOP] ** 2).mean()))
            after = float(np.sqrt((seg ** 2).mean()))
            if before > 1e-5:
                ratios.append(after / before)
    if not ratios:
        return 0.0, 0.0, 0.0
    return (float(np.median(ratios)), float(np.mean(ratios)), len(ratios))


print("%-24s %12s %12s %8s" % ("版本", "尾巴中位比", "尾巴均值比", "样本数"))
for f, label in PAIRS:
    p = os.path.join(D, f)
    if not os.path.exists(p):
        print("%-24s （缺）" % label)
        continue
    med, mean, cnt = tail_ratio(p)
    print("%-24s %11.3f %12.3f %8d" % (label, med, mean, cnt))
print("\n（尾巴比＝骤降后 300ms 内 RMS ÷ 骤降前 RMS；越小越不浑浊）")
