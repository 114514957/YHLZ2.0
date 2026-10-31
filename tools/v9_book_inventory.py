#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""图书素材清点：把 下载物象/图书素材 下的 .nb 分章文件建成索引。

只读，不改原文。产出 cache/book_index.json 供后续取用。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "下载物象", "图书素材")
OUT = os.path.join(ROOT, "cache", "book_index.json")


def read_text(p: str) -> tuple[str, str]:
    raw = open(p, "rb").read()
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def guess_title(text: str) -> str:
    """取首个非空行；若很短且不含标点，当章节标题。"""
    for line in text.splitlines()[:4]:
        s = line.strip()
        if s:
            if len(s) <= 40 and not re.search(r"[。！？，]", s):
                return s
            return ""
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isdir(SRC):
        print("目录不存在:", SRC)
        return 2

    index = []
    print("=" * 78)
    print("图书素材清点")
    print("=" * 78)
    grand_chars = 0
    for book in sorted(os.listdir(SRC)):
        bdir = os.path.join(SRC, book)
        if not os.path.isdir(bdir):
            continue
        files = sorted(f for f in os.listdir(bdir) if f.endswith(".nb"))
        encs = Counter()
        chars = 0
        titled = 0
        chapters = []
        for f in files:
            p = os.path.join(bdir, f)
            text, enc = read_text(p)
            encs[enc] += 1
            chars += len(text)
            title = guess_title(text)
            if title:
                titled += 1
            chapters.append({"file": f, "chars": len(text), "title": title,
                             "path": os.path.relpath(p, ROOT)})
        grand_chars += chars
        print("\n【%s】" % book)
        print("  章节 %d ｜ 字符 %s ｜ 平均 %.0f 字/章"
              % (len(files), format(chars, ","), chars / max(len(files), 1)))
        print("  编码: %s" % dict(encs))
        print("  有章节标题的: %d / %d" % (titled, len(files)))
        if chapters:
            print("  首章: %s ｜ %s" % (chapters[0]["file"], chapters[0]["title"] or "(无标题)"))
            print("  末章: %s ｜ %s" % (chapters[-1]["file"], chapters[-1]["title"] or "(无标题)"))
        index.append({"book": book, "dir": os.path.relpath(bdir, ROOT),
                      "chapters": len(files), "chars": chars,
                      "encodings": dict(encs), "files": chapters})

    print("\n" + "=" * 78)
    print("四本合计：章节 %d ｜ 字符 %s（约 %.1f 万汉字）"
          % (sum(b["chapters"] for b in index), format(grand_chars, ","),
             grand_chars / 10000))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"source": os.path.relpath(SRC, ROOT), "total_chars": grand_chars,
                   "books": index}, fh, ensure_ascii=False, indent=1)
    print("索引已存: %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
