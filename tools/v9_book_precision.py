#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""随机抽样核对台词归属（跨章节），用原文段落人工判定精确率。"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")


def paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[。！？…”」])\s{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    kw = sys.argv[1] if len(sys.argv) > 1 else "诡秘"
    target = sys.argv[2] if len(sys.argv) > 2 else "奥黛丽"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 20261018

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if kw in x["book"]), None)
    tag = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", b["book"])[:12]
    samp_file = os.path.join(ROOT, "cache", "book_dialogue_v4_%s.json" % tag)
    samp = json.load(io.open(samp_file, encoding="utf-8"))
    pool = samp["samples"].get(target, [])
    print("== %s ｜ %s ｜ 池 %d 条 ==" % (b["book"], target, len(pool)))
    random.seed(seed)
    picks = random.sample(pool, min(n, len(pool)))

    # 建 章节号 → 文本 的映射（用文件名前 5 位）
    byfile = {}
    for ch in b["files"]:
        byfile[ch["file"][:5]] = os.path.join(ROOT, ch["path"])

    for key, line in picks:
        p = byfile.get(key)
        if not p:
            print("\n（找不到章节 %s）" % key)
            continue
        text = io.open(p, encoding="utf-8", errors="replace").read()
        paras = paragraphs(text)
        hit = -1
        for i, para in enumerate(paras):
            if line[:16] in para:
                hit = i
                break
        print("\n" + "=" * 70)
        print("章节 %s ｜ 声称说话人: 【%s】" % (key, target))
        if hit < 0:
            print("  未能定位段落")
            continue
        print("  该段: %s" % paras[hit][:220])
        if hit > 0:
            print("  上段: %s" % paras[hit - 1][-120:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
