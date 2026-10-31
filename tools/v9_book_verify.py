#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工具验收：抽样核对台词归属是否准确（打印台词前后原文，供人工判断）。"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")
QUOTE = re.compile(r"[“「]([^”」]{2,240})[”」]")
VERBS = r"(?:说道|问道|答道|笑道|喊道|叫道|轻声|低声|叹道|说|道|问|答|喊|笑|叹)"


def who_said(text: str, start: int, end: int, names: list[str]) -> str:
    before = text[max(0, start - 30):start]
    for n in names:
        if re.search(re.escape(n) + VERBS + r"[^\u4e00-\u9fa5]{0,3}$", before):
            return n
        if re.search(re.escape(n) + r"[^\u4e00-\u9fa50-9]{0,2}$", before) and "：" in before[-3:]:
            return n
    after = text[end:end + 20]
    for n in names:
        if re.match(r"^[\s，,]*" + re.escape(n) + VERBS, after):
            return n
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    kw = sys.argv[1] if len(sys.argv) > 1 else "希灵"
    names = (sys.argv[2] if len(sys.argv) > 2 else "珊多拉,林雪").split(",")
    n_want = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if kw in x["book"]), None)
    if not b:
        print("没找到")
        return 2

    pool = []
    for ch in b["files"]:
        p = os.path.join(ROOT, ch["path"])
        text = io.open(p, encoding="utf-8", errors="replace").read()
        for m in QUOTE.finditer(text):
            spk = who_said(text, m.start(), m.end(), names)
            if spk:
                pool.append((ch["file"][:5], spk, m.group(1), text, m.start(), m.end()))
    print("== %s ｜ 可判定台词的候选池 %d 条 ==" % (b["book"], len(pool)))
    random.seed(20261018)
    sample = random.sample(pool, min(n_want * len(names), len(pool)))

    for f, spk, line, text, s, e in sample:
        ctx_b = text[max(0, s - 70):s].replace("\n", " ")
        ctx_a = text[e:e + 50].replace("\n", " ")
        print("\n--- 判定说话人: 【%s】 章节 %s ---" % (spk, f))
        print("  上文: …%s" % ctx_b)
        print("  台词: 「%s」" % line)
        print("  下文: %s…" % ctx_a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
