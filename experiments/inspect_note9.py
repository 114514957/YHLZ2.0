# -*- coding: utf-8 -*-
"""解开老爹新发的笔记包，看清里面是什么。"""
from __future__ import annotations

import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ZIP = (r"C:\Users\ACE_WAN——PROJECT\Documents\xwechat_files"
       r"\wxid_3vjj1zzjrs0w22_538f\msg\file\2026-11\无标题笔记_9.zip")
OUT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\_inbox\note9"

print("存在：%s｜%.1f KB" % (os.path.exists(ZIP), os.path.getsize(ZIP) / 1024 if os.path.exists(ZIP) else 0))
os.makedirs(OUT, exist_ok=True)
with zipfile.ZipFile(ZIP) as z:
    print("\n条目 %d：" % len(z.namelist()))
    for i in z.infolist():
        print("   %-50s %8.1f KB" % (i.filename[:50], i.file_size / 1024))
    z.extractall(OUT)

print("\n=== 文本预览 ===")
for root, _d, files in os.walk(OUT):
    for f in sorted(files):
        p = os.path.join(root, f)
        rel = os.path.relpath(p, OUT)
        size = os.path.getsize(p)
        print("\n" + "=" * 68)
        print("%s（%.1f KB）" % (rel, size / 1024))
        if size > 200 * 1024:
            print("（太大，跳过预览）")
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except Exception as ex:  # noqa: BLE001
            print("读不了：%s" % ex)
            continue
        print(t[:1200])
