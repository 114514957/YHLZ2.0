#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""改写前体检：520 个"元亨提问"块里有哪些声音特征需要校正（只读）。"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")

# 利贞标记（对调后会落入元亨嘴里 → 必须清）
LIZHEN_MARKS = ["理论上来说", "理论上", "从原理上"]
# 元亨自称（对调后可能落入利贞嘴里 → 必须清）
YUAN_SELF = ["本小姐", "老娘", "咱家"]
BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = os.path.join(MAT, "对话样本.md")
    txt = io.open(p, encoding="utf-8", errors="replace").read()
    parts = re.split(r"^##\s+", txt, flags=re.M)[1:]

    n_blocks = 0
    lz_mark_in_answer = Counter()
    blocks_with_lz_mark = 0
    yuan_self_in_answer = Counter()
    banned_in_answer = Counter()
    banned_in_question = Counter()
    ans_len = []
    q_len = []

    for b in parts:
        turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)\d*\s*\n(.*?)(?=^###|\Z)",
                           b, re.M | re.S)
        if not turns or (turns[0][0], turns[0][1]) != ("元亨", "问"):
            continue
        n_blocks += 1
        hit_lz = False
        for spk, kind, body in turns:
            body = body.strip()
            if kind == "问":
                q_len.append(len(body))
                for w in BANNED:
                    if w in body:
                        banned_in_question[w] += 1
            else:
                ans_len.append(len(body))
                for w in LIZHEN_MARKS:
                    if w in body:
                        lz_mark_in_answer[w] += 1
                        hit_lz = True
                for w in YUAN_SELF:
                    if w in body:
                        yuan_self_in_answer[w] += 1
                for w in BANNED:
                    if w in body:
                        banned_in_answer[w] += 1
        if hit_lz:
            blocks_with_lz_mark += 1

    print("=" * 76)
    print("520 个待改块体检")
    print("=" * 76)
    print("块数: %d" % n_blocks)
    print("\n利贞口头禅出现在答轮（对调后会进元亨嘴，需清）:")
    print("  ", dict(lz_mark_in_answer) or "无")
    print("  含该口头禅的块: %d (%.0f%%)" % (blocks_with_lz_mark,
                                       100.0 * blocks_with_lz_mark / max(n_blocks, 1)))
    print("\n元亨自称出现在答轮（对调后会进他人嘴，需清）:")
    print("  ", dict(yuan_self_in_answer) or "无")
    print("\n禁词出现在答轮:", dict(banned_in_answer) or "无")
    print("禁词出现在问轮:", dict(banned_in_question) or "无")
    if ans_len:
        ans_len.sort()
        print("\n答轮长度: 中位 %d 字，均值 %.0f，最长 %d"
              % (ans_len[len(ans_len) // 2], sum(ans_len) / len(ans_len), ans_len[-1]))
    if q_len:
        q_len.sort()
        print("问轮长度: 中位 %d 字，均值 %.0f，最长 %d"
              % (q_len[len(q_len) // 2], sum(q_len) / len(q_len), q_len[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
