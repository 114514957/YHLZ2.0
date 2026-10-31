#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小说内容抽样：每本随机抽 N 段，打印出来人工判性质。"""
from __future__ import annotations

import io
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SRC = os.path.join(ROOT, "下载物象", "图书素材")
IDX = os.path.join(ROOT, "cache", "book_index.json")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    span = int(sys.argv[2]) if len(sys.argv) > 2 else 420
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261020
    idx = json.load(io.open(IDX, encoding="utf-8"))
    rng = random.Random(seed)
    for b in idx["books"]:
        files = b["files"]
        picks = rng.sample(files, min(n, len(files)))
        print("\n" + "=" * 88)
        print("【%s】随机抽 %d 段" % (b["book"], len(picks)))
        for ch in picks:
            p = os.path.join(ROOT, ch["path"])
            text = io.open(p, encoding="utf-8", errors="replace").read()
            start = max(0, len(text) // 3)
            seg = text[start:start + span].replace("\n", " ").strip()
            print("\n  --- %s（第 %d/%d 字起）---" % (ch["file"][:5], start, len(text)))
            print("  " + seg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
