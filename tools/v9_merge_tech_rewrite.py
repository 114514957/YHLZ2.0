#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合并技术块改写结果，核对覆盖度，并生成整合后的新文件。

- 按块头 `## 对话-N｜技术` 匹配；
- 未被改写覆盖的块列出，供补跑；
- 生成 `docs/素材/_修订/对话样本_技术块改写版_20261018.md`（不覆盖原文件）。
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")
REV = os.path.join(MAT, "_修订")


def block_key(block: str) -> str:
    return block.split("\n", 1)[0].strip()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 1) 收集改写结果
    rewrites: dict[str, str] = {}
    dup = []
    files = sorted(f for f in os.listdir(REV) if f.startswith("技术块改写_"))
    for f in files:
        txt = io.open(os.path.join(REV, f), encoding="utf-8", errors="replace").read()
        for b in re.split(r"(?m)^##\s+", txt)[1:]:
            block = "## " + b.strip() + "\n"
            k = block_key(block)
            if k in rewrites:
                dup.append(k)
            rewrites[k] = block
    print("修订文件 %d 个｜改写块 %d 个（去重后 %d）｜重复键 %d"
          % (len(files), len(rewrites) + len(dup), len(rewrites), len(dup)))

    # 2) 原文件里待改的块
    src = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8", errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", src)
    needs, missing = [], []
    new_parts = []
    for b in parts:
        block = "## " + b.rstrip() + "\n"
        turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)", block, re.M)
        if turns and turns[0] == ("元亨", "问"):
            k = block_key(block)
            needs.append(k)
            if k in rewrites:
                new_parts.append(rewrites[k])
            else:
                missing.append(k)
                new_parts.append(block)
        else:
            new_parts.append(block)

    print("原文件待改块 %d｜已覆盖 %d｜未覆盖 %d"
          % (len(needs), len(needs) - len(missing), len(missing)))
    if missing:
        print("未覆盖的块（需补跑）:")
        for k in missing[:30]:
            print("   ", k)

    # 3) 写整合文件
    out = os.path.join(REV, "对话样本_技术块改写版_20261018.md")
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(head.rstrip() + "\n")
        for p in new_parts:
            fh.write("\n" + p.rstrip() + "\n")
    print("\n已生成: %s（%d 块）" % (os.path.relpath(out, ROOT), len(new_parts)))

    # 4) 校验整合后还有多少"首轮元亨问"
    txt2 = io.open(out, encoding="utf-8", errors="replace").read()
    still = 0
    for b in re.split(r"(?m)^##\s+", txt2)[1:]:
        block = "## " + b
        t = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)", block, re.M)
        if t and t[0] == ("元亨", "问"):
            still += 1
    print("整合后仍有「首轮元亨问」的块: %d（应等于未覆盖数 %d）" % (still, len(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
