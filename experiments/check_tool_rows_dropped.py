# -*- coding: utf-8 -*-
"""查：v13 清洗时，带 tool_calls 的样本有没有被误杀（这是工具题集体掉分的头号嫌疑）。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OLD = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10", "sft_persona_v9t10_train.jsonl")
NEW = os.path.join(ROOT, "dist", "material_v13", "sft_persona_v13_train.jsonl")


def stats(p: str) -> dict:
    n = tool = empty_ans = 0
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        n += 1
        ms = [m for m in (r.get("messages") or []) if isinstance(m, dict)]
        has_tc = any(m.get("tool_calls") for m in ms)
        last = ms[-1] if ms else {}
        ans = str(last.get("content") or "").strip()
        if has_tc:
            tool += 1
        if last.get("role") == "assistant" and not ans:
            empty_ans += 1
    return {"n": n, "tool_rows": tool, "empty_ans": empty_ans}


old = stats(OLD)
new = stats(NEW)
print("v9t10：%d 条｜带 tool_calls %d 条｜末条 assistant 空内容 %d 条"
      % (old["n"], old["tool_rows"], old["empty_ans"]))
print("v13  ：%d 条｜带 tool_calls %d 条｜末条 assistant 空内容 %d 条"
      % (new["n"], new["tool_rows"], new["empty_ans"]))
print("\n工具样本变化：%+d 条" % (new["tool_rows"] - old["tool_rows"]))

# 再查：v13 里还有多少"工具相关"（source 里带 tool，或消息里出现 tool 角色）
src = Counter()
tool_role = 0
for ln in io.open(NEW, encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    r = json.loads(ln)
    src[str(r.get("source"))] += 1
    if any(m.get("role") == "tool" for m in (r.get("messages") or []) if isinstance(m, dict)):
        tool_role += 1
print("v13 里含 tool 角色消息的样本：%d 条" % tool_role)
print("v13 来源里带 tool 字样的：%s"
      % {k: v for k, v in src.items() if "tool" in str(k).lower()})
