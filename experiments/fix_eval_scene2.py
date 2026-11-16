# -*- coding: utf-8 -*-
"""修评测器：场景变体预渲染 + 逐题选（原来在循环外用了未定义的 u）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "experiments", "eval56_28.py")
t = io.open(P, encoding="utf-8").read()

old_persona = ('    sys_p = _render(False, u)\n'
               '    anchor_p = TA.anchor_for(sys_p) if anchor else ""\n'
               '    for e in PB.PERSONA_BANK:\n'
               '        u = e["q"]\n')
new_persona = ('    # 2026-11-16（台账 1259）：按场景选系统提示——闲聊只载必要块。\n'
               '    sys_p_casual = _render(False, "在吗")\n'
               '    sys_p_work = _render(False, "帮我查一下台账 1259")\n'
               '    sys_p = sys_p_casual\n'
               '    anchor_p = TA.anchor_for(sys_p) if anchor else ""\n'
               '    for e in PB.PERSONA_BANK:\n'
               '        u = e["q"]\n'
               '        try:\n'
               '            from backend import prompt_scene as _psc\n'
               '            sys_p = sys_p_work if _psc.classify(u) == "work" else sys_p_casual\n'
               '        except Exception:  # noqa: BLE001\n'
               '            sys_p = sys_p_casual\n')
assert old_persona in t, "persona 段没匹配"
t = t.replace(old_persona, new_persona, 1)

old_group = ('    sys_g = _render(True, u)\n'
             '    anchor_g = TA.anchor_for(sys_g) if anchor else ""\n'
             '    for e in GB.GROUP_BANK:\n'
             '        msgs = e.get("messages") or []\n'
             '        u = "\\n".join(str(m.get("content") or "") if isinstance(m, dict) else str(m)\n'
             '                      for m in msgs) or str(e.get("scene") or "")\n')
new_group = ('    sys_g = _render(True, "在群里说一句")\n'
             '    anchor_g = TA.anchor_for(sys_g) if anchor else ""\n'
             '    for e in GB.GROUP_BANK:\n'
             '        msgs = e.get("messages") or []\n'
             '        u = "\\n".join(str(m.get("content") or "") if isinstance(m, dict) else str(m)\n'
             '                      for m in msgs) or str(e.get("scene") or "")\n')
assert old_group in t, "group 段没匹配"
t = t.replace(old_group, new_group, 1)

io.open(P, "w", encoding="utf-8").write(t)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已修评测器；编译：", "OK" if r.returncode == 0 else "失败")
if r.returncode != 0:
    print((r.stderr or "")[-300:])
