# -*- coding: utf-8 -*-
"""度量：一次请求的 token 都花在哪（系统提示各块 / 工具 / 历史）。

目的：提示词瘦身与工具按需加载要有数，不能拍脑袋。
用法：python tools/measure_llm_tokens.py
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "llm_workbench"))

from transformers import AutoTokenizer  # noqa: E402

TOK = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf",
                                                "gemma-4-e4b-it"))


def n(text: str) -> int:
    return len(TOK(str(text or ""), add_special_tokens=False)["input_ids"])


print("=== ① 系统提示（私聊）===")
from backend import target_prompts as TP  # noqa: E402

sysp = TP.render_system_prompt(public=False)
print("   总 %d 字 / %d token" % (len(sysp), n(sysp)))

print("\n=== ② 按块拆（找大头）===")
rows = []
for name in dir(TP):
    if not name.isupper() or name.startswith("_"):
        continue
    val = getattr(TP, name)
    if not isinstance(val, str) or len(val) < 120:
        continue
    rows.append((n(val), len(val), name))
for tok, chars, name in sorted(rows, reverse=True)[:12]:
    print("   %5d token｜%5d 字｜%s" % (tok, chars, name))

print("\n=== ③ 工具 schema ===")
try:
    import evals as EV  # llm_workbench
    tools = EV.load_tools()
    print("   总数 %d 个｜全部 token %d" % (len(tools), n(json.dumps(tools, ensure_ascii=False))))
    per = []
    for t in tools:
        per.append((n(json.dumps(t, ensure_ascii=False)), t.get("function", {}).get("name", "?")))
    per.sort(reverse=True)
    print("   单工具最大 5 个：%s" % [(nm, tk) for tk, nm in per[:5]])
    print("   均值 %.0f token/个" % (sum(tk for tk, _ in per) / len(per)))
except Exception as ex:  # noqa: BLE001
    print("   读不到：%s" % ex)

print("\n=== ④ 一次真实请求的构成（实测口径）===")
print("   上一轮实测「在吗」：in 6039 token")
print("   其中系统提示 %d，剩下约 %d = 工具 + 历史 + 用户话"
      % (n(sysp), 6039 - n(sysp)))
