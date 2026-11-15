# -*- coding: utf-8 -*-
"""把生产提示词原样导出来，并按 512 滑窗标注：哪一条落在"看不见"的区域。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend import prompt_overrides as PO  # noqa: E402
from backend import target_prompts as TP  # noqa: E402

OUT = os.path.join(ROOT, "docs", "研究", "提示词")
os.makedirs(OUT, exist_ok=True)

# 真 tokenizer（只加载分词器，不加载权重）
tok = None
try:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(
        os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it"))
    print("tokenizer 已加载（真实 token 计数）")
except Exception as ex:  # noqa: BLE001
    print("tokenizer 不可用（用 1.5 字/token 估算）：%s" % type(ex).__name__)


def ntok(s: str) -> int:
    if tok is not None:
        return len(tok.encode(s, add_special_tokens=False))
    return int(len(s) / 1.5)


for public in (False, True):
    text = TP.render_system_prompt(public=public)
    tag = "群聊" if public else "私聊"
    path = os.path.join(OUT, "%s_系统提示_20261114.txt" % tag)
    io.open(path, "w", encoding="utf-8").write(text)

    total_tok = ntok(text)
    cutoff = max(0, total_tok - 512)     # 滑窗层看得见的分界（以 token 计）
    print("\n" + "=" * 76)
    print("%s系统提示：%d 字｜%d token｜滑窗可见起点 = token #%d 之后"
          % (tag, len(text), total_tok, cutoff))
    print("=" * 76)

    rows = []
    for key, title in PO.EDITABLE.items():
        cur = PO.override(key, "")
        if not cur:
            # 没覆盖时去渲染结果里找默认文本
            cur = getattr(TP, key, "") or ""
        if not cur:
            continue
        pos = text.find(cur)
        if pos < 0:
            continue
        start_tok = ntok(text[:pos])
        end_tok = start_tok + ntok(cur)
        rows.append((start_tok, end_tok, key, title, len(cur)))

    # 段落标题也标出来
    for line in text.splitlines():
        if line.startswith("【"):
            pos = text.find(line)
            rows.append((ntok(text[:pos]), ntok(text[:pos]) + ntok(line),
                         "—", line.strip("【】"), len(line)))

    rows.sort()
    print("   %-6s %-6s %-30s %-9s %s" % ("起tok", "止tok", "块", "字数", "滑窗层可见?"))
    for s, e, key, title, ln in rows:
        vis = "✅ 完全可见" if s >= cutoff else ("◐ 部分可见" if e > cutoff else "❌ 看不见")
        print("   %-6d %-6d %-30s %-9d %s" % (s, e, (title or key)[:30], ln, vis))

    print("\n   —— 原文（前 700 字）——")
    print("\n".join("   " + ln for ln in text[:700].splitlines()))
    print("   ...（完整见 %s）" % os.path.join("docs", "研究", "提示词",
                                              os.path.basename(path)))
