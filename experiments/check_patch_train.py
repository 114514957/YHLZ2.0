# -*- coding: utf-8 -*-
"""看本地补丁训练还在不在、跑到哪。"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "models", "lora", "yuanheng-stylepatch1")

out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
                      "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
print("显存/利用率：%s" % out)

ps = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get",
                     "ProcessId,CommandLine", "/format:list"],
                    capture_output=True, text=True, errors="replace").stdout
hits = [ln for ln in ps.splitlines() if "finetune_train" in ln]
print("训练进程：%s" % ("在跑" if hits else "没有"))
for h in hits[:2]:
    print("   %s" % h.strip()[:120])

print("\n产物目录：%s" % ("存在" if os.path.isdir(OUT) else "还没建"))
if os.path.isdir(OUT):
    for f in sorted(os.listdir(OUT))[:8]:
        print("   %-36s %d" % (f, os.path.getsize(os.path.join(OUT, f))))

log = os.path.join(YH, "experiments", "runs", "stylepatch_train.log")
print("\n日志：")
for p in glob.glob(os.path.join(YH, "dist", "**", "train_summary.json"), recursive=True):
    if "stylepatch" in p:
        print("   " + p)
