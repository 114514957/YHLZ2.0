#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析"元亨提问"块的结构与场景分布，为改写做准备（只读）。"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    for fname in ("对话样本.md", "记忆样本_v2.md", "优质样本.md"):
        p = os.path.join(MAT, fname)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8", errors="replace").read()
        parts = re.split(r"^##\s+", txt, flags=re.M)[1:]
        cats = Counter()
        patterns = Counter()
        bad = []
        for b in parts:
            head = b.split("\n", 1)[0].strip()
            turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)\d*", b, re.M)
            if not turns or turns[0] != ("元亨", "问"):
                continue
            # 场景标签：标题里的"｜xxx"
            m = re.search(r"[｜|]([^｜|\s]+)\s*$", head)
            cats[m.group(1) if m else "(无标签)"] += 1
            # 发言模式：把序列压成字符串
            pat = "".join(("Y" if s == "元亨" else "L" if s == "利贞" else "D") +
                          ("q" if k == "问" else "a") for s, k in turns)
            patterns[pat] += 1
            bad.append(head)
        print("=" * 80)
        print("%s ｜ 首轮元亨问的块: %d" % (fname, len(bad)))
        print("  场景分布:", dict(cats.most_common(12)))
        print("  发言模式 Top8:")
        for pat, n in patterns.most_common(8):
            print("     %-18s %4d 次" % (pat, n))
        print("  前 8 个块标题:", bad[:8])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
