# -*- coding: utf-8 -*-
"""补回 _NONWORD（上一版编辑时被我删掉了）并跑一遍情报卡。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "qq_intel.py")
t = io.open(P, encoding="utf-8").read()
if "_NONWORD = re.compile" not in t:
    t = t.replace("_CN = re.compile",
                  '_NONWORD = re.compile(r"[\\s\\W_]+")\n_CN = re.compile', 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("已补回 _NONWORD")
else:
    print("_NONWORD 已存在")
print("编译：", end="")
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("OK" if r.returncode == 0 else "失败")
r = subprocess.run([sys.executable, "-X", "utf8", P], cwd=ROOT,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[:1800])
if r.returncode != 0:
    print("stderr:", r.stderr[-400:])
