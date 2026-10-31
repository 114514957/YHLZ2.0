#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按候选名逐个统计出现次数 + 台词条数，确定要研读的角色。"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")
QUOTE = re.compile(r"[“「]([^”」]{2,240})[”」]")

CANDIDATES = {
    "希灵": ["珊多拉", "潘多拉", "林雪", "浅浅", "冰蒂斯", "蕾娜", "艾玛", "卡莉",
             "陈俊", "洛丽塔", "贝拉", "米莉", "西卡罗", "盖亚", "维斯卡", "郝仁"],
    "异常": ["郝仁", "薇薇安", "莉莉", "伊扎克斯", "南风", "小黑", "大黑", "白水",
             "渡鸦", "莉莉丝", "许浅浅", "小丫头"],
    "诡秘": ["奥黛丽", "克莱恩", "阿尔杰", "梅丽莎", "班森", "佛尔思", "休", "艾辛格",
             "贝尔纳黛", "嘉德丽雅", "特莉丝", "伊莲"],
    "苏菲": ["苏菲", "艾伯特", "乔安", "席德", "阿尔贝托"],
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    idx = json.load(io.open(IDX, encoding="utf-8"))
    for kw, names in CANDIDATES.items():
        b = next((x for x in idx["books"] if kw in x["book"]), None)
        if not b:
            continue
        cnt = {n: 0 for n in names}
        dial = {n: 0 for n in names}
        scanned = 0
        for ch in b["files"]:
            p = os.path.join(ROOT, ch["path"])
            text = io.open(p, encoding="utf-8", errors="replace").read()
            scanned += 1
            for n in names:
                c = text.count(n)
                if c:
                    cnt[n] += c
            for m in QUOTE.finditer(text):
                before = text[max(0, m.start() - 40):m.start()]
                for n in names:
                    if n in before[-16:]:
                        dial[n] += 1
                        break
        print("\n== %s（%d 章）==" % (b["book"], scanned))
        rows = sorted(cnt.items(), key=lambda kv: -kv[1])
        for n, c in rows:
            if c:
                print("   %-8s 出现 %6d 次 ｜ 疑似台词 %5d 条" % (n, c, dial[n]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
