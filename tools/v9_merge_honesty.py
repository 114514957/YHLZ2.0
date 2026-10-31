#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把诚实边界改写稿合并回 诚实边界样本.md（按 `## b3-N` 键匹配）。"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
MAT = os.path.join(ROOT, "docs", "素材")
REV = os.path.join(MAT, "_修订")


def main() -> int:
    files = [f for f in os.listdir(REV) if f.startswith("诚实边界改写_")]
    rew = {}
    for f in files:
        txt = io.open(os.path.join(REV, f), encoding="utf-8", errors="replace").read()
        for b in re.split(r"(?m)^##\s+", txt)[1:]:
            blk = "## " + b.strip() + "\n"
            rew[blk.split("\n", 1)[0].strip()] = blk
    print("改写稿 %d 个文件｜块 %d" % (len(files), len(rew)))

    src = io.open(os.path.join(MAT, "诚实边界样本.md"), encoding="utf-8",
                  errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", src)
    used, keep = 0, []
    new = []
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        k = blk.split("\n", 1)[0].strip()
        if k in rew:
            new.append(rew[k])
            used += 1
        else:
            new.append(blk)
            keep.append(k)
    print("原块 %d｜替换 %d｜沿用 %d" % (len(parts), used, len(keep)))
    out = os.path.join(MAT, "诚实边界样本.md")
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(head.rstrip() + "\n")
        for p in new:
            fh.write("\n" + p.rstrip() + "\n")
    print("已写回:", os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
