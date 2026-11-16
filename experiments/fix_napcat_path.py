# -*- coding: utf-8 -*-
"""修 napcat_window 的 shell 路径（YH → YHLZ → PROJECT，往上两级）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "console_server.py")
t = io.open(P, encoding="utf-8").read()

old = '                shell = _PROJECT_ROOT.parent / "qqwatch" / "shell"'
new = ('                # YH → YHLZ → PROJECT（往上两级）；两条候选路径都试，避免再算错\n'
       '                _cands = [_PROJECT_ROOT.parent.parent / "qqwatch" / "shell",\n'
       '                          _PROJECT_ROOT.parent / "qqwatch" / "shell"]\n'
       '                shell = next((c for c in _cands\n'
       '                              if (c / "launcher-user.bat").exists()), _cands[0])')
assert old in t, "定位失败"
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(t)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已修路径；编译:", "OK" if r.returncode == 0 else "失败")
