# -*- coding: utf-8 -*-
"""全盘找今天新增的大文件（>5GB），定位老爹拉的产物。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOTS = [r"C:\Users\ACE_WAN——PROJECT", r"D:\\"]
CUT = time.time() - 20 * 3600
MIN = 5 << 30

for root in ROOTS:
    if not os.path.isdir(root):
        continue
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in
                   ("$Recycle.Bin", "System Volume Information", "node_modules", ".git")]
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size >= MIN and st.st_mtime >= CUT:
                print("%-88s %6.2f GB  %s" % (p, st.st_size / 1e9,
                                              time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))))
