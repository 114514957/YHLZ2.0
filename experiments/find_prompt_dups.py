# -*- coding: utf-8 -*-
"""找 16 个渲染块之间的**逐字重复**（零信息损失的删减对象）。"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from transformers import AutoTokenizer  # noqa: E402

from backend import target_prompts as TP  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf",
                                                "gemma-4-e4b-it"))


def n(s: str) -> int:
    return len(tok(str(s or ""), add_special_tokens=False)["input_ids"])


sysp = TP.render_system_prompt(public=False)
flat = sysp.replace("\n", " ")

blocks = {}
for name in dir(TP):
    if not name.isupper() or name.startswith("_"):
        continue
    v = getattr(TP, name)
    if not isinstance(v, str) or len(v) < 100:
        continue
    probe = v.strip().replace("\n", " ")[:36]
    if probe and probe in flat:
        blocks[name] = v

# 按句切（中文句末标点）
sent = re.compile(r"[^。！？；\n]+[。！？；]?")
owner: dict[str, list[str]] = defaultdict(list)
for name, text in blocks.items():
    for s in sent.findall(text):
        s2 = s.strip()
        if len(s2) >= 8:
            owner[s2].append(name)

dups = {s: names for s, names in owner.items()
        if len(names) > 1 and len(set(names)) > 1}
print("渲染块：%d｜不同句子：%d｜**跨块重复：%d 句**"
      % (len(blocks), len(owner), len(dups)))
save = sum(n(s) * (len(set(v)) - 1) for s, v in dups.items())
print("删掉重复副本可省：约 %d token（占系统提示 %.0f%%）\n"
      % (save, 100.0 * save / max(1, n(sysp))))

for s, names in list(dups.items())[:12]:
    print("  「%s」" % s[:46])
    print("     出现于：%s" % "、".join(sorted(set(names))))
