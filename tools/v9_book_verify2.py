#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核对 v2 抽出的台词：回原文打印所在段落及其前后段，供人工判断归属。"""
from __future__ import annotations

import io
import json
import os
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
    book_kw = sys.argv[1] if len(sys.argv) > 1 else "诡秘"
    target = sys.argv[2] if len(sys.argv) > 2 else "奥黛丽"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if book_kw in x["book"]), None)
    samp_path = os.path.join(ROOT, "cache",
                             sys.argv[4] if len(sys.argv) > 4 else "book_dialogue_v3.json")
    samp = json.load(io.open(samp_path, encoding="utf-8"))
    lines = [l for _, l in samp["samples"].get(target, [])][:n]
    print("样本来自:", os.path.basename(samp_path), "｜条数:", len(samp["samples"].get(target, [])))

    for want in lines:
        found = False
        for ch in b["files"]:
            p = os.path.join(ROOT, ch["path"])
            text = io.open(p, encoding="utf-8", errors="replace").read()
            i = text.find(want[:22])
            if i < 0:
                continue
            found = True
            paras = paragraphs(text)
            # 找到包含该片段的段落序号
            acc = 0
            hit_idx = 0
            for k, para in enumerate(paras):
                if want[:14] in para:
                    hit_idx = k
                    break
            print("\n" + "=" * 72)
            print("章节 %s ｜ 目标台词:「%s…」" % (ch["file"][:5], want[:40]))
            for k in range(max(0, hit_idx - 2), min(len(paras), hit_idx + 2)):
                mark = ">>>" if k == hit_idx else "   "
                print("%s [%d] %s" % (mark, k, paras[k][:190]))
            break
        if not found:
            print("\n（未定位到:「%s…」）" % want[:30])
    return 0


if __name__ == "__main__":
    sys.exit(main())
