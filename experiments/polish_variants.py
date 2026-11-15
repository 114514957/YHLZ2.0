# -*- coding: utf-8 -*-
"""三档精修强度（轻/中/重），交给老爹耳朵挑。"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
D = os.path.join(ROOT, "音频素材", "分离试听", "赤蛮奇")
SRC = os.path.join(D, "7_干声_去混响+谱减.wav")

VARIANTS = [
    ("8a_精修_轻", 0.4, 0.35, 0.20, 1.3),
    ("8b_精修_中", 0.6, 0.50, 0.35, 1.6),
    ("8c_精修_重", 0.85, 0.70, 0.50, 2.2),
]

for name, dm, dh, cp, dv in VARIANTS:
    out = os.path.join(D, name + ".wav")
    r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "tools", "svc_vocal_polish.py"),
                        SRC, out,
                        "--de-metallic", str(dm), "--de-harsh", str(dh),
                        "--comp", str(cp), "--drive", str(dv)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        print("%-12s 失败：%s" % (name, (r.stderr or "")[-200:]))
        continue
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        print("%-12s 输出解析失败" % name)
        continue
    print("%-12s 峰值 %+5.1f dB｜削波 %d｜crest %.2f→%.2f｜刺耳比 %.3f→%.3f"
          % (name, d["peak_db"], d["clip"], d["crest_before"], d["crest_after"],
             d["harsh_2k5_4k5_ratio_before"], d["harsh_2k5_4k5_ratio"]))
