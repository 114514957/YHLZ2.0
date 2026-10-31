#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合并风格重做稿，核对覆盖度，生成整合文件。"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")
REV = os.path.join(MAT, "_修订")


def key_of(block: str) -> str:
    return block.split("\n", 1)[0].strip()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files = sorted(f for f in os.listdir(REV) if f.startswith("风格重做_"))
    rewrites: dict[str, str] = {}
    dup = 0
    for f in files:
        txt = io.open(os.path.join(REV, f), encoding="utf-8", errors="replace").read()
        for b in re.split(r"(?m)^##\s+", txt)[1:]:
            block = "## " + b.strip() + "\n"
            k = key_of(block)
            if k in rewrites:
                dup += 1
            rewrites[k] = block
    print("重做文件 %d 个｜改写块 %d（去重 %d，重复键 %d）"
          % (len(files), len(rewrites) + dup, len(rewrites), dup))

    src = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8",
                  errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", src)
    total = len(parts)
    used, missing, new_parts = 0, [], []
    for b in parts:
        block = "## " + b.rstrip() + "\n"
        k = key_of(block)
        if k in rewrites:
            new_parts.append(rewrites[k])
            used += 1
        else:
            new_parts.append(block)
            missing.append(k)
    print("原块 %d｜已用重做稿 %d｜沿用原稿 %d（%.1f%%）"
          % (total, used, len(missing), 100.0 * used / total))
    if missing:
        print("沿用原稿的块（前 10）:", missing[:10])

    out = os.path.join(REV, "对话样本_风格重做版_20261018.md")
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(head.rstrip() + "\n")
        for p in new_parts:
            fh.write("\n" + p.rstrip() + "\n")
    print("\n已生成: %s（%d 块）" % (os.path.relpath(out, ROOT), len(new_parts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
