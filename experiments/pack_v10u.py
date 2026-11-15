# -*- coding: utf-8 -*-
"""生成 v10u 的 MANIFEST 并打包。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")

man = {
    "version": "v10u",
    "purpose": "在破限基座上重训：既写得动，又守住 r07/r08",
    "base": "TrevorJS/gemma-4-E4B-it-uncensored",
    "data": {"total": 6916, "sigma_w": 3651, "guard_upweighted": 288, "vulgar_real": 7},
    "known_gaps": {"style_ref": "素材表两条指向 TEMP 目录，文件已被清理",
                   "golden_new": 0},
    "trainer": "v9t11 修复版（weight 重采样/丢超长/公共前缀 mask/fp32 计算/无 load_best）",
    "expected": {"steps": 741, "minutes": "45-50", "trainable_params": "34.9M",
                 "adapter_mb": 139.6},
}
with io.open(os.path.join(PKG, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(man, f, ensure_ascii=False, indent=1)
print("MANIFEST 写好")

tar = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u.tar.gz")
if os.path.exists(tar):
    os.remove(tar)
subprocess.run(["tar", "-czf", tar, "retrain_pkg_gemma_v10u"],
               cwd=os.path.join(YH, "dist"), check=True)
print("打包 %d 字节" % os.path.getsize(tar))
out = subprocess.run(["tar", "-tzf", tar], capture_output=True, text=True).stdout
print(out.strip())
