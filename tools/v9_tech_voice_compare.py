#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对照：技术类块里，元亨当答者 vs 利贞当答者的发言风格差异（只读）。"""
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
    txt = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8", errors="replace").read()
    parts = re.split(r"^##\s+", txt, flags=re.M)[1:]

    tech = [b for b in parts if b.split("\n", 1)[0].strip().endswith("技术")]
    print("技术块总数: %d" % len(tech))

    yuan_main = []   # 元亨是主答者
    lz_main = []     # 利贞是主答者
    for b in tech:
        turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)\d*\s*\n(.*?)(?=^###|\Z)",
                           b, re.M | re.S)
        ya = sum(len(t[2]) for t in turns if t[0] == "元亨" and t[1] == "答")
        la = sum(len(t[2]) for t in turns if t[0] == "利贞" and t[1] == "答")
        if ya > la:
            yuan_main.append(b)
        elif la > ya:
            lz_main.append(b)

    print("  元亨主答的技术块: %d" % len(yuan_main))
    print("  利贞主答的技术块: %d" % len(lz_main))

    def sample(blocks, who, n=2):
        for b in blocks[:n]:
            head = b.split("\n", 1)[0].strip()
            print("\n  --- %s ---" % head)
            turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)\d*\s*\n(.*?)(?=^###|\Z)",
                               b, re.M | re.S)
            for spk, kind, body in turns:
                if kind == "答" and spk == who:
                    print("    [%s答] %s" % (spk, body.strip()[:180]))
                    break

    print("\n=== 元亨当答者的技术块样例（这是我们要的风格）===")
    sample(yuan_main, "元亨")
    print("\n=== 利贞当答者的技术块样例（这是要改的）===")
    sample(lz_main, "利贞")
    return 0


if __name__ == "__main__":
    sys.exit(main())
