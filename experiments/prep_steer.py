# -*- coding: utf-8 -*-
"""① 找「哇」类 token 的 id（logit-bias 用）② 写 GBNF 语法（禁问号结尾）③ 测日记。"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=== 1. 找 token ===")
from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it"))
for w in ("哇", "哇哦", "哇哈", "哇哈哈", "哦", "哎呦"):
    ids = tok.encode(w, add_special_tokens=False)
    print("  %-6s → %s ｜解码回验：%s" % (w, ids, [tok.decode([i]) for i in ids]))

print("\n=== 2. 写 GBNF（禁问号结尾）===")
GBNF = r"""root  ::= piece* tail
piece ::= [^?？\n]
tail  ::= [^?？\n]
"""
p = os.path.join(YH, "experiments", "no_question.gbnf")
with io.open(p, "w", encoding="utf-8") as f:
    f.write(GBNF)
print("  %s" % p)
print("  规则：整段输出允许含问号（piece），但**最后一个字符不能是问号**（tail）")
