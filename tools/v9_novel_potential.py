#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小说素材产出潜力评估：量化每本书能抽出多少可用素材。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")
QUOTE = re.compile(r"[“「]([^”」]{4,300})[”」]")
# 观点/论断句（苏菲类）：含"认为/主张/意思是/指的是/本质/意义/概念"
OPINION = re.compile(r"[^。！？\n]{0,60}(?:认为|主张|指的是|意思是|本质|意义|概念|哲学|理性|实体|自由|道德|存在)[^。！？\n]{0,60}[。！？]")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    idx = json.load(io.open(IDX, encoding="utf-8"))
    print("=" * 92)
    print("小说素材产出潜力（按章统计可抽取单元）")
    print("=" * 92)
    print("%-28s %8s %10s %10s %10s %10s" % ("书", "章", "万字", "对白条", "观点句", "对白/万字"))
    tot = Counter()
    out = {}
    for b in idx["books"]:
        chars = 0
        nq = 0
        nop = 0
        for ch in b["files"]:
            t = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                        errors="replace").read()
            chars += len(t)
            nq += len(QUOTE.findall(t))
            nop += len(OPINION.findall(t))
        w = chars / 10000
        print("%-28s %8d %10.1f %10d %10d %10.0f"
              % (b["book"][:26], b["chapters"], w, nq, nop, nq / max(w, 1e-9)))
        out[b["book"]] = {"chapters": b["chapters"], "chars": chars,
                          "quotes": nq, "opinions": nop}
        tot["q"] += nq
        tot["op"] += nop
        tot["chars"] += chars

    print("\n四本合计：对白 %s 条 ｜ 观点句 %s 条 ｜ %s 万字"
          % (format(tot["q"], ","), format(tot["op"], ","), format(tot["chars"] / 10000, ",.0f")))

    print("\n【若转成元亨素材，理论上限（按 3 条对白/1 条素材，且只取 20% 精品）】")
    for k, v in out.items():
        est = int(v["quotes"] / 3 * 0.20)
        print("  %-28s 约 %s 条对话素材 ｜ 观点素材约 %s 条"
              % (k[:26], format(est, ","), format(int(v["opinions"] * 0.3), ",")))
    est_all = int(tot["q"] / 3 * 0.20)
    print("  %-28s 约 %s 条" % ("合计（对话）", format(est_all, ",")))
    print("\n对照：V9 目标 80,000 条，现有 3,875 条。")
    print("      单靠四本书的理论上限 ≈ %s 条，**够用但有版权与失真风险**。"
          % format(est_all, ","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
