#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核对：元亨作为提问方的真实分布（区分"首轮提问"与"中途插问"）。

- 首轮就是元亨问 → 严重违规（元亨成了求教者，主体性被夺）
- 中途才元亨问 → 可能是合理的追问，需人判
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")

H2 = re.compile(r"^##\s+(.+)$", re.M)
H3 = re.compile(r"^###\s*(元亨|利贞|老爹)\s*(问|答)", re.M)


def analyze(path: str) -> dict:
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    # 按 ## 切块
    blocks = re.split(r"^##\s+", txt, flags=re.M)[1:]
    first_ask_yuan = 0
    mid_ask_yuan = 0
    total_blocks = 0
    samples_first = []
    for b in blocks:
        total_blocks += 1
        turns = H3.findall(b)
        if not turns:
            continue
        asks = [(i, spk) for i, (spk, kind) in enumerate(turns) if kind == "问"]
        if not asks:
            continue
        first_speaker_kind = turns[0]
        if first_speaker_kind == ("元亨", "问"):
            first_ask_yuan += 1
            if len(samples_first) < 3:
                head = b.split("\n")[0][:40]
                samples_first.append(head)
        else:
            for i, spk in asks:
                if spk == "元亨":
                    mid_ask_yuan += 1
                    break
    return {"file": os.path.basename(path), "blocks": total_blocks,
            "first_ask_yuan": first_ask_yuan, "mid_ask_yuan": mid_ask_yuan,
            "samples": samples_first}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 86)
    print("元亨提问分布核对（块 = `## `）")
    print("=" * 86)
    tot_f = tot_m = tot_b = 0
    for name in sorted(os.listdir(MAT)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(MAT, name)
        txt = io.open(p, encoding="utf-8", errors="replace").read()
        if "元亨问" not in txt:
            continue
        r = analyze(p)
        if not r["blocks"]:
            continue
        print("\n%s" % r["file"])
        print("  块数 %d ｜ **首轮即元亨问 %d 块（%.0f%%）** ｜ 中途元亨问 %d 块"
              % (r["blocks"], r["first_ask_yuan"],
                 100.0 * r["first_ask_yuan"] / r["blocks"], r["mid_ask_yuan"]))
        for s in r["samples"]:
            print("     例: %s" % s)
        tot_f += r["first_ask_yuan"]
        tot_m += r["mid_ask_yuan"]
        tot_b += r["blocks"]
    print("\n" + "=" * 86)
    print("合计：块 %d ｜ 首轮即元亨问 **%d** 块（%.1f%%）｜ 中途元亨问 %d 块"
          % (tot_b, tot_f, 100.0 * tot_f / max(tot_b, 1), tot_m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
