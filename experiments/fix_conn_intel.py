# -*- coding: utf-8 -*-
"""补回 _conn（被上一版编辑吃掉）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "qq_intel.py")
t = io.open(P, encoding="utf-8").read()
if "def _conn(" not in t:
    t = t.replace("def _kw(",
                  'def _conn():\n'
                  '    """打开 memstore（只读查询用）。"""\n'
                  '    con = sqlite3.connect(str(DB), timeout=2.0)\n'
                  '    con.row_factory = sqlite3.Row\n'
                  '    return con\n\n\n'
                  'def _kw(', 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("已补回 _conn")
else:
    print("_conn 已存在")
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("编译：", "OK" if r.returncode == 0 else "失败")
r = subprocess.run([sys.executable, "-X", "utf8", P], cwd=ROOT,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[:2000])
if r.returncode != 0:
    print("stderr:", r.stderr[-500:])
