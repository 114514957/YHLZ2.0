# -*- coding: utf-8 -*-
"""挖 v1..v9 的历史训练证据：老 zip 包、v8 adapter、56 题对照报告。"""
from __future__ import annotations

import glob
import io
import os
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=" * 72)
print("① 老训练包 zip 里有没有配置/日志")
print("=" * 72)
for z in sorted(glob.glob(os.path.join(ROOT, "dist", "finetune_bundle_v*.zip"))):
    try:
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            interesting = [n for n in names
                           if re.search(r"(config|train_log|summary|\.json|\.csv|\.md)$", n)]
            print("\n   %s（%d 个文件）" % (os.path.basename(z), len(names)))
            for n in interesting[:12]:
                print("      %-56s %8d B" % (n[:56], zf.getinfo(n).file_size))
    except Exception as ex:  # noqa: BLE001
        print("   %s 读失败 %s" % (os.path.basename(z), ex))

print()
print("=" * 72)
print("② v8 adapter 目录内容")
print("=" * 72)
d = os.path.join(ROOT, "dist", "v8_adapter")
if os.path.isdir(d):
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        print("   %-40s %10d B" % (f, os.path.getsize(p)))
else:
    print("   没有 v8_adapter 目录")

print()
print("=" * 72)
print("③ 56 题实测对照报告里的版本/分数")
print("=" * 72)
p = os.path.join(ROOT, "docs", "报告", "V9_56题实测对照_20261027.md")
if os.path.exists(p):
    t = io.open(p, encoding="utf-8", errors="replace").read()
    lines = [ln.rstrip() for ln in t.splitlines()
             if re.search(r"(v\d|得分|/\s*56|\|\s*\d+\s*\|)", ln)]
    for ln in lines[:40]:
        print("   " + ln[:150])
else:
    print("   没找到该报告")

print()
print("=" * 72)
print("④ 人格回归明细里出现过的版本")
print("=" * 72)
for f in sorted(glob.glob(os.path.join(ROOT, "docs", "报告", "人格回归明细_*.md"))):
    print("   " + os.path.basename(f))
