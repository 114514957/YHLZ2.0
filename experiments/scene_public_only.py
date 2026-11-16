# -*- coding: utf-8 -*-
"""只对「群聊」裁剪（私聊保持全量）。

依据（三次实验的一致形状）：
  工具 -35% → 私聊 -7、群聊 +1~2
  提示词压缩 -13% → 私聊 -5、群聊 +3
  整块裁剪 -29% → 私聊 -10、群聊 +2~3
→ 结论：她的人格靠「整包指导」撑着，私聊不能减；而群聊要的正是短与不反问，减了反而更好。
→ 落地：`droppable_names(scene, public)` 只在 public=True 时返回可丢块。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① prompt_scene：加 public 参数
P1 = os.path.join(ROOT, "backend", "prompt_scene.py")
t = io.open(P1, encoding="utf-8").read()
old = '''def droppable_names(scene: str) -> tuple[str, ...]:
    if not enabled() or scene != "casual":
        return ()
    return DROP_IN_CASUAL'''
new = '''def droppable_names(scene: str, public: bool = False) -> tuple[str, ...]:
    """哪些块可以不发。

    2026-11-16（台账 1260）：**只在群聊（public）裁剪**。
    三次实验一致显示：任何"减负"都让私聊人格掉分（-5~-10）、群聊反而升（+2~3），
    所以私聊保持全量，群聊才裁。
    """
    if not enabled() or scene != "casual" or not public:
        return ()
    return DROP_IN_CASUAL'''
assert old in t, "droppable_names 没匹配"
t = t.replace(old, new, 1)
io.open(P1, "w", encoding="utf-8").write(t)
print("① prompt_scene 已加 public 条件")

# ② target_prompts：把 public 传进去
P2 = os.path.join(ROOT, "backend", "target_prompts.py")
u = io.open(P2, encoding="utf-8").read()
old2 = '_names = _ps.droppable_names(str(scene or ""))'
new2 = '_names = _ps.droppable_names(str(scene or ""), bool(public))'
assert old2 in u, "调用没匹配"
u = u.replace(old2, new2, 1)
io.open(P2, "w", encoding="utf-8").write(u)
print("② target_prompts 已传 public")

r = subprocess.run([sys.executable, "-m", "py_compile", P1, P2], cwd=ROOT)
print("编译：", "OK" if r.returncode == 0 else "失败")
