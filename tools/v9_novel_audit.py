#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小说素材内容审查：把宪章规则用到 1898 万字小说上。

审四件事：
  A 一档红线（identity/mission/memory/harm/porn）——命中即该章不可直接用于素材
  B 二档语境词（自杀/杀人/毒品/攻击/去人性化/隐私）——只登记，逐条看语境
  C 高风险密度——每万字命中数，判断整本是否"过脏"
  D 可用性估算——扣掉红线章后还剩多少可用文字

用法：
    python tools/v9_novel_audit.py [--json out.json] [--sample 3]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SRC = os.path.join(ROOT, "下载物象", "图书素材")

import v9_constitution_scan as CS  # noqa: E402


def read(p: str) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(ROOT, "cache", "novel_audit.json"))
    ap.add_argument("--sample", type=int, default=2, help="每本书每类红线打印几条样例")
    a = ap.parse_args()

    print("=" * 90)
    print("小说素材内容审查（宪章一档硬红线 + 二档语境词）")
    print("=" * 90)

    grand = Counter()
    out = {}
    for book in sorted(os.listdir(SRC)):
        bdir = os.path.join(SRC, book)
        if not os.path.isdir(bdir):
            continue
        files = sorted(f for f in os.listdir(bdir) if f.endswith(".nb"))
        chars = 0
        hard_hits = Counter()
        soft_hits = Counter()
        hot_chapters = set()
        samples: dict[str, list[str]] = defaultdict(list)
        for f in files:
            text = read(os.path.join(bdir, f))
            chars += len(text)
            for tier, rule, matched in CS.scan_text(text):
                if tier == "hard":
                    hard_hits[rule] += 1
                    hot_chapters.add(f[:5])
                    if len(samples[rule]) < a.sample:
                        i = text.find(matched)
                        s = max(0, i - 40)
                        samples[rule].append("%s：…%s…" % (f[:5], text[s:i + len(matched) + 40].replace("\n", " ")))
                else:
                    soft_hits[rule] += 1
                    if len(samples["soft:" + rule]) < a.sample:
                        i = text.find(matched)
                        s = max(0, i - 40)
                        samples["soft:" + rule].append("%s：…%s…" % (f[:5], text[s:i + len(matched) + 40].replace("\n", " ")))

        hard_total = sum(hard_hits.values())
        soft_total = sum(soft_hits.values())
        usable = chars - (chars / max(len(files), 1) * len(hot_chapters))
        print("\n【%s】" % book)
        print("  章节 %d ｜ 字符 %s ｜ 一档命中 %d（涉 %d 章，%.2f%%）｜ 二档命中 %d"
              % (len(files), format(chars, ","), hard_total, len(hot_chapters),
                 100.0 * len(hot_chapters) / max(len(files), 1), soft_total))
        print("  一档分布: %s" % (dict(hard_hits.most_common()) or "无"))
        print("  二档分布: %s" % (dict(soft_hits.most_common(6)) or "无"))
        print("  密度: 一档 %.3f / 万字 ｜ 扣红线章后可用约 %s 字"
              % (hard_total / (chars / 10000), format(int(usable), ",")))
        for rule, ex in samples.items():
            if rule.startswith("soft:"):
                continue
            print("  · %s 样例：" % rule)
            for e in ex:
                print("      %s" % e[:150])
        grand["chars"] += chars
        grand["hard"] += hard_total
        grand["soft"] += soft_total
        grand["hot"] += len(hot_chapters)
        out[book] = {"chapters": len(files), "chars": chars,
                     "hard": dict(hard_hits), "soft": dict(soft_hits),
                     "hot_chapters": sorted(hot_chapters),
                     "usable_est": int(usable),
                     "samples": {k: v for k, v in samples.items()}}

    print("\n" + "=" * 90)
    print("四本合计：字符 %s ｜ 一档 %d ｜ 二档 %d ｜ 涉红线章 %d"
          % (format(grand["chars"], ","), grand["hard"], grand["soft"], grand["hot"]))
    with io.open(a.json, "w", encoding="utf-8") as fh:
        json.dump({"grand": dict(grand), "books": out}, fh, ensure_ascii=False, indent=1)
    print("明细: %s" % os.path.relpath(a.json, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
