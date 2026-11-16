# -*- coding: utf-8 -*-
"""评测器也按场景渲染提示词（否则测不到裁剪的影响）。"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "experiments", "eval56_28.py")
t = io.open(P, encoding="utf-8").read()

# 找到 render_system_prompt 的调用（persona 与 group 两处）
hits = re.findall(r"TP\.render_system_prompt\([^)]*\)", t)
print("原有调用：", hits[:4])

helper = '''
def _render(public: bool, text: str) -> str:
    """按场景渲染（YHLZ_PROMPT_SCENE=1 时，闲聊不载入开发/工具类块）。"""
    scene = ""
    try:
        from backend import prompt_scene as _psc
        if _psc.enabled():
            scene = _psc.classify(text)
    except Exception:  # noqa: BLE001
        scene = ""
    try:
        return TP.render_system_prompt(public=public, scene=scene)
    except TypeError:
        return TP.render_system_prompt(public=public)
'''

if "_render(public" not in t:
    anchor = "def call("
    t = t.replace(anchor, helper.strip() + "\n\n\n" + anchor, 1)

# 替换调用
t2 = re.sub(r"TP\.render_system_prompt\(public=False\)", "_render(False, u)", t)
t2 = re.sub(r"TP\.render_system_prompt\(public=True\)", "_render(True, u)", t2)
n_change = len(re.findall(r"_render\(", t2))
io.open(P, "w", encoding="utf-8").write(t2)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已改评测器（_render 出现 %d 次）；编译：%s"
      % (n_change, "OK" if r.returncode == 0 else "失败"))
if r.returncode != 0:
    print((r.stderr or "")[-400:])
