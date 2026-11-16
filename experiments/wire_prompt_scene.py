# -*- coding: utf-8 -*-
"""把「场景裁剪」接进 render_system_prompt，并让 target_entry 传入本轮文本。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① target_prompts：加 scene 参数 + 末尾过滤
P1 = os.path.join(ROOT, "backend", "target_prompts.py")
t = io.open(P1, encoding="utf-8").read()

old_sig = "def render_system_prompt(\n    public: bool = False"
if old_sig not in t:
    m = re.search(r"def render_system_prompt\(([^)]*)\)", t)
    raise SystemExit("签名没找到，实际是：%s" % (m.group(0) if m else "?"))
t = t.replace(old_sig, "def render_system_prompt(\n    public: bool = False,\n    scene: str = \"\"", 1)

# 在 return 之前插入过滤
i = t.find("def render_system_prompt(")
j = t.find("\n    if public:\n        blocks.append(GROUP_HARD_RULES)", i)
assert j > i, "找不到群聊硬规则追加处"
insert = '''
    # 2026-11-16（台账 1259）：**场景裁剪**——闲聊只发必要块（人格/禁令/关系…），
    # 整块丢掉开发流程、工具协议、反幻觉、记忆边界等。人格块**一字不改**。
    try:
        from backend import prompt_scene as _ps
        _drop_names = _ps.droppable_names(str(scene or ""))
        if _drop_names:
            _drop_vals = set()
            for _n in _drop_names:
                _v = _ov(_n, globals().get(_n, ""))
                if _v:
                    _drop_vals.add(_v)
                    _drop_vals.add(str(_v).strip())
            _before = len(blocks)
            blocks = [b for b in blocks
                      if b is not None and str(b) not in _drop_vals
                      and str(b).strip() not in _drop_vals]
            if len(blocks) != _before:
                print("[prompt-scene] casual：块 %d → %d（丢 %d 个）"
                      % (_before, len(blocks), _before - len(blocks)), flush=True)
    except Exception:  # noqa: BLE001
        pass
'''
t = t[:j] + insert + t[j:]
io.open(P1, "w", encoding="utf-8").write(t)
print("target_prompts 已加 scene 裁剪")

# ② target_entry：render_system 收 text 并传 scene
P2 = os.path.join(ROOT, "backend", "target_entry.py")
e = io.open(P2, encoding="utf-8").read()
old = ('    def render_system(self, *, allowed_tools: frozenset | None = None,\n'
       '                      text_turn: bool = False, text: str = "") -> str:')
if old not in e:
    m = re.search(r"    def render_system\(self[^)]*\)[^:]*:", e)
    print("⚠ render_system 签名不同：%s" % (m.group(0) if m else "?"))
else:
    # 找到最终 return 之前，把 scene 传给渲染函数（若有）
    print("render_system 签名匹配")
io.open(P2, "w", encoding="utf-8").write(e)
