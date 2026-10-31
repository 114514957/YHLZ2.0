#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按角色/关键词在图书素材里抽原文片段（只读，不改原文）。

用途：①核对原文可用性；②按《原文引用与防失真规则》取"观点/性质"原文句。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 3:
        print("用法: v9_book_extract.py <书名关键词> <角色名或关键词> [最多条数]")
        return 2
    book_kw, kw = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    idx = json.load(io.open(IDX, encoding="utf-8"))
    books = [b for b in idx["books"] if book_kw in b["book"]]
    if not books:
        print("没找到书:", book_kw, "｜可选:", [b["book"] for b in idx["books"]])
        return 2
    b = books[0]
    print("== %s ｜ 关键词「%s」==" % (b["book"], kw))

    hits = 0
    files_scanned = 0
    for ch in b["files"]:
        p = os.path.join(ROOT, ch["path"])
        text = io.open(p, encoding="utf-8", errors="replace").read()
        files_scanned += 1
        if kw not in text:
            continue
        # 抽含关键词的句子（按中文句末切）
        for m in re.finditer(r"[^。！？\n]{0,80}" + re.escape(kw) + r"[^。！？\n]{0,80}[。！？]?", text):
            s = m.group(0).strip()
            if len(s) < 12:
                continue
            print("\n  [%s] %s" % (ch["file"][:5], ch["title"] or "(无题)"))
            print("     %s" % s)
            hits += 1
            if hits >= limit:
                print("\n（已达上限 %d 条；扫描 %d 章）" % (limit, files_scanned))
                return 0
    print("\n共 %d 条（扫描 %d 章）" % (hits, files_scanned))
    return 0


if __name__ == "__main__":
    sys.exit(main())
