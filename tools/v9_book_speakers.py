#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统计一本书里"说话人候选"（引号前后出现的姓名）的出现次数，用于确定研读角色。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")
# 姓名候选：2-4 个汉字紧跟"说/道/问/答/喊/笑/叹"或出现在引号前后
NAME_NEAR = re.compile(r"([\u4e00-\u9fa5]{2,4})(?:说|道|问|答|喊|叫道|笑道|叹气|摇头|点头)")
QUOTE_NEAR = re.compile(r"[“「]([^”」]{2,200})[”」]\s*([\u4e00-\u9fa5]{2,4})(?:说|道)")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    kw = sys.argv[1] if len(sys.argv) > 1 else "希灵"
    topn = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if kw in x["book"]), None)
    if not b:
        print("没找到:", kw)
        return 2
    c = Counter()
    scanned = 0
    for ch in b["files"][:400]:
        p = os.path.join(ROOT, ch["path"])
        text = io.open(p, encoding="utf-8", errors="replace").read()
        scanned += 1
        for m in NAME_NEAR.finditer(text):
            c[m.group(1)] += 1
        for m in QUOTE_NEAR.finditer(text):
            c[m.group(2)] += 1
    # 过滤明显不是人名的
    stop = {"什么", "这个", "那个", "怎么", "这样", "他们", "我们", "你们", "自己",
            "时候", "东西", "问题", "大家", "现在", "之后", "然后", "只是", "可是"}
    items = [(k, v) for k, v in c.most_common(200) if k not in stop and len(k) >= 2]
    print("== %s ｜ 扫描 %d 章 ｜ 说话人候选 TOP%d ==" % (b["book"], scanned, topn))
    for k, v in items[:topn]:
        print("   %-6s %5d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
