# -*- coding: utf-8 -*-
"""解开老爹发来的资料包，看清里面是什么（不猜）。"""
from __future__ import annotations

import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ZIP = (r"C:\Users\ACE_WAN——PROJECT\Documents\xwechat_files"
       r"\wxid_3vjj1zzjrs0w22_538f\msg\file\2026-11\Gemma3n-E4B_资料包_20261109(1).zip")
OUT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\_inbox\gemma3n_e4b"

os.makedirs(OUT, exist_ok=True)
with zipfile.ZipFile(ZIP) as z:
    names = z.namelist()
    print("压缩包 %d 个条目｜%.1f KB\n" % (len(names), os.path.getsize(ZIP) / 1024))
    for info in z.infolist():
        flag = "目录" if info.is_dir() else "%8.1f KB" % (info.file_size / 1024)
        print("  %-52s %s" % (info.filename[:52], flag))
    z.extractall(OUT)

print("\n解到：%s\n" % OUT)
print("=== 文本文件内容预览 ===")
for root, _dirs, files in os.walk(OUT):
    for f in files:
        p = os.path.join(root, f)
        rel = os.path.relpath(p, OUT)
        if os.path.getsize(p) > 400 * 1024:
            print("\n--- %s（%.0f KB，跳过预览）" % (rel, os.path.getsize(p) / 1024))
            continue
        print("\n--- %s ---" % rel)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception as ex:  # noqa: BLE001
            print("  读不了：%s" % ex)
            continue
        print(txt[:1500])
