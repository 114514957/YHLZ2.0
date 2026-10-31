#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小说专用内容规则全量扫描（比宪章运行时护栏更贴合小说文本）。

为什么另立规则：宪章一档匹配的是"教我自杀"这种**请求句式**，小说不这么写；
小说用**描写**。所以这里按"露骨性/血腥渲染/危险细节/毒品/现实教唆"五类重建。

做法：全量扫 4,940 章（远超国标 5% 抽样），命中的逐段打印供人工判。
"""
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
    # 一类：露骨性描写（不是"色情"这个词，是描写本身）
    "性露骨": r"赤裸|下体|性交|交媾|呻吟|高潮|勃起|脱光|揉搓|爱抚|胴体|媚肉",
    # 二类：血腥渲染（不是"血"这个字，是渲染式描写）
    "血腥渲染": r"肠子|脑浆|血肉模糊|肢解|开膛|剖腹|内脏流|碎肉|脑髓",
    # 三类：危险物制作细节（配方/步骤 + 危险物）
    "危险细节": r"(?:制作|合成|配方|步骤|剂量).{0,12}(?:炸药|炸弹|毒药|毒品|冰毒|枪支)|(?:炸药|炸弹).{0,12}(?:配方|步骤|克数)",
    # 四类：毒品
    "毒品": r"吸毒|大麻|冰毒|海洛因|摇头丸|注射毒品",
    # 五类：现实教唆（针对真实人物的伤害方法）
    "现实教唆": r"怎么(?:自杀|杀人|下毒|绑架)|教你(?:自杀|杀人|诈骗)|(?:自杀|杀人).{0,6}(?:方法|步骤)",
}

idx = json.load(io.open(IDX, encoding="utf-8"))
grand = Counter()
report = {}
for b in idx["books"]:
    hits = Counter()
    samples: dict[str, list[str]] = {}
    hot = set()
    for ch in b["files"]:
        t = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8", errors="replace").read()
        for tag, pat in RULES.items():
            for m in re.finditer(pat, t):
                hits[tag] += 1
                hot.add(ch["file"][:5])
                lst = samples.setdefault(tag, [])
                if len(lst) < 3:
                    s = max(0, m.start() - 60)
                    lst.append("%s …%s…" % (ch["file"][:5], t[s:m.end() + 60].replace("\n", " ")))
    print("\n【%s】章 %d ｜命中 %d ｜涉 %d 章"
          % (b["book"][:26], len(b["files"]), sum(hits.values()), len(hot)))
    for tag, n in hits.most_common():
        print("   %-8s %4d" % (tag, n))
    for tag, ex in samples.items():
        for e in ex:
            print("     [%s] %s" % (tag, e[:150]))
    report[b["book"]] = {"chapters": len(b["files"]), "hits": dict(hits),
                         "hot": sorted(hot), "samples": samples}
    for k, v in hits.items():
        grand[k] += v

print("\n" + "=" * 84)
print("四本合计：" + (" ｜ ".join("%s %d" % (k, v) for k, v in grand.most_common()) or "全部 0 命中"))
io.open(os.path.join(ROOT, "cache", "novel_rules_scan.json"), "w",
        encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=1))
print("明细: cache/novel_rules_scan.json")
