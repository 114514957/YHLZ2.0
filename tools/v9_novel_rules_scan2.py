#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小说内容精修扫描（v2）：排除中文常见误伤，给出可信的风险密度。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
IDX = os.path.join(ROOT, "cache", "book_index.json")

RULES = {
    # 血腥：排除 直肠子/花花肠子/肠子悔青（性格与懊悔）、肢解+器械
    "血腥渲染": r"(?<!直)(?<!花花)肠子(?!悔)|脑浆|脑髓(?!里)|血肉模糊|开膛|剖腹|内脏(?:流|外露)",
    # 性露骨：排比喻（赤裸裸的+抽象名词）、拳击（赤裸上身+搏斗）
    "性露骨": r"下体|性交|交媾|勃起|胴体|媚肉|爱抚.{0,10}(?:乳房|胸|大腿)|脱光.{0,6}(?:衣服|衣裤)",
    # 毒品：排除 麻烦/麻木/麻利/麻辣
    "毒品": r"吸毒|(?<![麻])大麻(?!烦)|冰毒|海洛因|摇头丸",
    # 危险细节
    "危险细节": r"(?:制作|合成|配方|步骤|剂量).{0,12}(?:炸药|炸弹|毒药|冰毒|枪支)",
    # 现实教唆：排除"阻止/防止/不要"语境
    "现实教唆": r"(?<!阻止)(?<!防止)怎么(?:自杀|杀人|下毒|绑架)|教你(?:自杀|杀人|诈骗)",
}

idx = json.load(io.open(IDX, encoding="utf-8"))
print("=" * 88)
print("小说内容精修扫描 v2（已排除常见中文误伤）")
print("=" * 88)
grand = Counter()
for b in idx["books"]:
    hits = Counter()
    hot = set()
    ex: dict[str, list[str]] = {}
    for ch in b["files"]:
        t = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8", errors="replace").read()
        for tag, pat in RULES.items():
            for m in re.finditer(pat, t):
                hits[tag] += 1
                hot.add(ch["file"][:5])
                lst = ex.setdefault(tag, [])
                if len(lst) < 2:
                    s = max(0, m.start() - 55)
                    lst.append("%s …%s…" % (ch["file"][:5], t[s:m.end() + 55].replace("\n", " ")))
    total = sum(hits.values())
    dens = total / (sum(len(io.open(os.path.join(ROOT, c["path"]), encoding="utf-8",
                                    errors="replace").read()) for c in b["files"]) / 10000)
    print("\n【%s】章 %d ｜命中 %d ｜涉 %d 章（%.1f%%）｜密度 %.2f/万字"
          % (b["book"][:26], len(b["files"]), total, len(hot),
             100.0 * len(hot) / len(b["files"]), dens))
    for tag, n in hits.most_common():
        print("   %-8s %4d" % (tag, n))
    for tag, lst in ex.items():
        for e in lst:
            print("     [%s] %s" % (tag, e[:140]))
    for k, v in hits.items():
        grand[k] += v
print("\n" + "=" * 88)
print("四本合计：" + (" ｜ ".join("%s %d" % kv for kv in grand.most_common()) or "全部 0"))
