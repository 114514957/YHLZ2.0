# -*- coding: utf-8 -*-
"""私聊(本体) vs 群聊 的系统提示词到底差在哪；以及两者用的是不是同一个模型。"""
from __future__ import annotations

import difflib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend.target_prompts import render_system_prompt  # noqa: E402

pri = render_system_prompt()
pub = render_system_prompt(public=True)
print("私聊(本体 owner) %d 字｜群聊(public) %d 字" % (len(pri), len(pub)))

a = [x for x in pri.splitlines() if x.strip()]
b = [x for x in pub.splitlines() if x.strip()]
diff = [x for x in difflib.unified_diff(a, b, lineterm="", n=0)
        if x[:1] in "+-" and not x.startswith(("+++", "---"))]
print("差异行 %d 条\n" % len(diff))
print("只在私聊出现的（群聊没有）：")
for x in diff:
    if x.startswith("-"):
        print("   - %s" % x[1:].strip()[:100])
print("\n只在群聊出现的（私聊没有）：")
for x in diff:
    if x.startswith("+"):
        print("   + %s" % x[1:].strip()[:100])

print("\n=== 模型侧：daemon 用哪个模型 ===")
for k in ("YH_LLM_BASE", "YHLZ_LLM_BASE", "OPENAI_BASE_URL", "YH_MODEL",
          "YHLZ_MODEL", "DEEPSEEK_API_KEY"):
    v = os.getenv(k)
    print("   %-18s %s" % (k, "已设置" if v else "未设置"))
