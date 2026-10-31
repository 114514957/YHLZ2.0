#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 客服腔_* 改写稿合并回各自的素材文件（按 `## 块名` 匹配）。"""
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
    groups: dict[str, dict[str, str]] = {}
    for f in sorted(os.listdir(REV)):
        if not f.startswith("客服腔_"):
            continue
        # 文件名：客服腔_<tag>_<start>-<end>_<time>.md
        m = re.match(r"客服腔_(.+?)_\d+-\d+_\d+\.md$", f)
        if not m:
            continue
        tag = m.group(1)
        txt = io.open(os.path.join(REV, f), encoding="utf-8", errors="replace").read()
        d = groups.setdefault(tag, {})
        for b in re.split(r"(?m)^##\s+", txt)[1:]:
            blk = "## " + b.strip() + "\n"
            d[blk.split("\n", 1)[0].strip()] = blk

    for tag, rew in groups.items():
        p = os.path.join(MAT, tag + ".md")
        if not os.path.exists(p):
            print("找不到目标文件: %s" % p)
            continue
        src = io.open(p, encoding="utf-8", errors="replace").read()
        head, *parts = re.split(r"(?m)^##\s+", src)
        used = 0
        new = []
        for b in parts:
            blk = "## " + b.rstrip() + "\n"
            k = blk.split("\n", 1)[0].strip()
            if k in rew:
                new.append(rew[k])
                used += 1
            else:
                new.append(blk)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(head.rstrip() + "\n")
            for x in new:
                fh.write("\n" + x.rstrip() + "\n")
        print("%-22s 改写稿 %d｜替换 %d / 总 %d" % (tag, len(rew), used, len(parts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
