#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽角色台词原文（引号内的话），供角色研读与"原文引用"素材使用。

只读，不修改原文。支持中文引号 “” 与 「」。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")

QUOTE = re.compile(r"[“「]([^”」]{2,240})[”」]")


def load_book(kw: str) -> dict | None:
    idx = json.load(io.open(IDX, encoding="utf-8"))
    for b in idx["books"]:
        if kw in b["book"]:
            return b
    return None


def iter_texts(book: dict):
    for ch in book["files"]:
        p = os.path.join(ROOT, ch["path"])
        yield ch, io.open(p, encoding="utf-8", errors="replace").read()


def who_said(text: str, start: int, end: int, names: list[str]) -> str:
    """严格判定说话人：姓名必须**紧邻**引号且带说话动词，否则不认。

    认的形态：
      ① 前：`珊多拉道：“`  `珊多拉说：“`  `林雪低声问：“`（姓名+动词+冒号，紧贴引号）
      ② 后：`”珊多拉说`  `”林雪道`（引号后紧跟姓名+动词）
    其它一律返回 ""（宁缺勿错——错归属会教错口吻）。
    """
    verbs = r"(?:说道|问道|答道|笑道|喊道|叫道|轻声|低声|叹道|说|道|问|答|喊|笑|叹)"
    before = text[max(0, start - 30):start]
    for n in names:
        if re.search(re.escape(n) + verbs + r"[^\u4e00-\u9fa5]{0,3}$", before):
            return n
        if re.search(re.escape(n) + r"[^\u4e00-\u9fa50-9]{0,2}$", before) and "：" in before[-3:]:
            return n
    after = text[end:end + 20]
    for n in names:
        m = re.match(r"^[\s，,]*" + re.escape(n) + verbs, after)
        if m:
            return n
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 3:
        print("用法: v9_book_dialogue.py <书名关键词> <角色1,角色2,...> [每角色条数]")
        return 2
    book_kw = sys.argv[1]
    names = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    b = load_book(book_kw)
    if not b:
        print("没找到书:", book_kw)
        return 2
    print("== %s ｜ 角色: %s ==" % (b["book"], "、".join(names)))

    got: dict[str, list[tuple[str, str]]] = {n: [] for n in names}
    scanned = 0
    for ch, text in iter_texts(b):
        scanned += 1
        for m in QUOTE.finditer(text):
            line = m.group(1).strip()
            if len(line) < 4:
                continue
            spk = who_said(text, m.start(), m.end(), names)
            if spk and len(got[spk]) < limit:
                got[spk].append((ch["file"][:5], line))
        if all(len(v) >= limit for v in got.values()):
            break

    for n in names:
        print("\n【%s】取样 %d 条（扫描 %d 章）" % (n, len(got[n]), scanned))
        for f, line in got[n]:
            print("   [%s] %s" % (f, line))

    out = os.path.join(ROOT, "cache", "book_dialogue_samples.json")
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump({"book": b["book"], "scanned": scanned,
                   "samples": {k: v for k, v in got.items()}}, fh,
                  ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
