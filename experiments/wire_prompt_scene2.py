# -*- coding: utf-8 -*-
"""场景裁剪接线（第二版，按真实签名改）。

1) render_system_prompt 加 `scene: str = ""`，在 return 前按场景丢块
2) target_entry.render_system 加 `text` 参数解析成 scene 并传入
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ── ① target_prompts ────────────────────────────────────────────
P1 = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P1, encoding="utf-8").read()

old_sig = ("    public: bool = False,\n"
           "    style_lines: Optional[Sequence[str]] = None,\n"
           ") -> str:")
new_sig = ("    public: bool = False,\n"
           "    style_lines: Optional[Sequence[str]] = None,\n"
           "    scene: str = \"\",\n"
           ") -> str:")
assert old_sig in t, "签名没匹配"
t = t.replace(old_sig, new_sig, 1)

old_ret = ('    if public:\n'
           '        blocks.append(_ov("GROUP_HARD_RULES", GROUP_HARD_RULES))\n'
           '\n'
           '    return "\\n".join(blocks).strip() + "\\n"')
new_ret = '''    if public:
        blocks.append(_ov("GROUP_HARD_RULES", GROUP_HARD_RULES))

    # 2026-11-16（台账 1259）：**场景裁剪**——闲聊只发必要块，人格块一字不改，
    # 整块丢掉开发流程/工具协议/反幻觉/记忆边界等。默认关闭（YHLZ_PROMPT_SCENE=1）。
    try:
        from backend import prompt_scene as _ps
        _names = _ps.droppable_names(str(scene or ""))
        if _names:
            _vals = set()
            for _n in _names:
                _v = _ov(_n, globals().get(_n, ""))
                if _v:
                    _vals.add(str(_v))
                    _vals.add(str(_v).strip())
            _n0 = len(blocks)
            blocks = [b for b in blocks
                      if b is not None and str(b) not in _vals
                      and str(b).strip() not in _vals]
            if len(blocks) != _n0:
                print("[prompt-scene] %s：块 %d → %d（丢 %d）"
                      % (scene, _n0, len(blocks), _n0 - len(blocks)), flush=True)
    except Exception:  # noqa: BLE001
        pass

    return "\\n".join(blocks).strip() + "\\n"'''
assert old_ret in t, "return 段没匹配"
t = t.replace(old_ret, new_ret, 1)
io.open(P1, "w", encoding="utf-8").write(t)
print("① target_prompts 已改")

# ── ② target_entry：把本轮文本变成 scene 传进去 ─────────────────
P2 = os.path.join(ROOT, "backend", "target_entry.py")
e = io.open(P2, encoding="utf-8").read()
old_call = ("        rendered = render_system_prompt(\n"
            "            persona=persona_arg, tools=tools,\n"
            "            public=not self._is_owner(),\n"
            "            style_lines=style_lines,\n"
            "        )")
new_call = ("        _scene = \"\"\n"
            "        try:\n"
            "            from backend import prompt_scene as _psc\n"
            "            if _psc.enabled():\n"
            "                _scene = _psc.classify(text or \"\")\n"
            "        except Exception:  # noqa: BLE001\n"
            "            _scene = \"\"\n"
            "        rendered = render_system_prompt(\n"
            "            persona=persona_arg, tools=tools,\n"
            "            public=not self._is_owner(),\n"
            "            style_lines=style_lines,\n"
            "            scene=_scene,\n"
            "        )")
assert old_call in e, "render_system_prompt 调用没匹配"
e = e.replace(old_call, new_call, 1)
io.open(P2, "w", encoding="utf-8").write(e)
print("② target_entry 已改")
