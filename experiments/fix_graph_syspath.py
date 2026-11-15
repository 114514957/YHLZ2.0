# -*- coding: utf-8 -*-
"""给 memory_graph 补 sys.path（否则 classify 导入失败，role 全 unknown）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "memory_graph.py")
t = io.open(P, encoding="utf-8").read()
if "sys.path.insert" not in t:
    if "\nimport sys" not in t:
        t = t.replace("import sqlite3\n", "import sqlite3\nimport sys\n", 1)
    anchor = 'DB = ROOT / "cache" / "memstore" / "memstore.db"'
    t = t.replace(anchor, anchor + "\nif str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))", 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("已补 sys.path")
else:
    print("已有 sys.path")

r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("编译:", "OK" if r.returncode == 0 else "失败")
r = subprocess.run([sys.executable, "-X", "utf8", P], cwd=ROOT,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
out = r.stdout or ""
print(out[:900])
if r.returncode != 0:
    print("stderr:", (r.stderr or "")[-300:])
