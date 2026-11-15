# -*- coding: utf-8 -*-
"""v10u 定版：写 MANIFEST、清掉误包的嵌套 tar、打包。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u.tar.gz")

nested = os.path.join(PKG, "retrain_pkg_gemma_v10u.tar.gz")
if os.path.exists(nested):
    os.remove(nested)
    print("删掉误包的嵌套 tar")
for junk in ("__pycache__",):
    d = os.path.join(PKG, junk)
    if os.path.isdir(d):
        import shutil
        shutil.rmtree(d)
        print("删掉 %s" % junk)


def lines(p):
    return sum(1 for x in io.open(p, encoding="utf-8") if x.strip())


tr = lines(os.path.join(PKG, "sft_persona_v10u_train.jsonl"))
va = lines(os.path.join(PKG, "sft_persona_v10u_val.jsonl"))

man = {
    "version": "v10u",
    "purpose": "在破限基座上重训：既写得动，又守住 r07/r08",
    "base": "TrevorJS/gemma-4-E4B-it-uncensored",
    "data": {"train": tr, "val": va, "total": tr + va, "sigma_w": 4504,
             "guard_sigma_w": 385, "vulgar_real": 7},
    "new_material": {"mat_对话样本": 1779, "mat_安全拒绝样本": 117,
                     "mat_哲学观点样本": 30, "mat_真实对话样本": 8},
    "overlap_finding": "docs/素材 4844 条里 57% 早已在包内（个性/黄金/开源/记忆/诚实边界 100% 覆盖）",
    "trainer": "v9t11 修复版",
    "expected": {"steps": 949, "minutes": "55-60", "trainable_params": "34.9M"},
}
with io.open(os.path.join(PKG, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(man, f, ensure_ascii=False, indent=1)

if os.path.exists(TAR):
    os.remove(TAR)
subprocess.run(["tar", "-czf", TAR, "retrain_pkg_gemma_v10u"],
               cwd=os.path.join(YH, "dist"), check=True)
print("train %d｜val %d｜包 %d 字节" % (tr, va, os.path.getsize(TAR)))
print(subprocess.run(["tar", "-tzf", TAR], capture_output=True, text=True).stdout.strip())
