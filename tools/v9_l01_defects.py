#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""L01 扩写批缺陷普查（只读）。

机械门控能过、但"读起来不对"的问题，用可判的代理指标扫出来：
  D1 同人连发：相邻两轮同一发言人（没有对方接话）
  D2 无问之答：某人的答N之前没有该人的问N（或没有任何问）——错位/拼接痕迹
  D3 近重复：同一块内两条发言高度重合（同一人复读或问答互换）
  D4 长议论串味：利贞单条发言 >120 字（人设是短句直给）
  D5 元亨立场串味：利贞发言里出现元亨口癖（哎/嘿/呦/咱/本小姐/！结尾堆叠）
用法：python tools/v9_l01_defects.py [文件]
"""
from __future__ import annotations

import io
import os
import re
import sys
from difflib import SequenceMatcher

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(PROJECT_ROOT, "docs", "素材", "_草稿", "L01_扩写30块_对话1至30_20261013.md")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
LIZHEN_HABITS = re.compile(r"哎|嘿|呦|咱|本小姐|好家伙|你猜怎么着")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with io.open(path, "r", encoding="utf-8") as fh:
        text = fh.read().replace("\r\n", "\n")
    blocks = [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]
    totals = {"D1": 0, "D2": 0, "D3": 0, "D4": 0, "D5": 0}
    flagged = []
    for blk in blocks:
        head = blk.splitlines()[0][3:].strip()
        ms = list(TURN.finditer(blk))
        ts = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            ts.append((m.group(1).strip(), m.group(2), blk[m.end():end].strip()))
        d1 = d2 = d3 = d4 = d5 = 0
        # D1 同人连发
        for i in range(1, len(ts)):
            if ts[i][0] == ts[i - 1][0]:
                d1 += 1
        # D2 无问之答：该发言人的答之前，从未出现过他的问
        asked = set()
        for sp, ty, tx in ts:
            if ty == "问":
                asked.add(sp)
            elif ty == "答" and sp not in asked:
                d2 += 1
        # D3 近重复（同块内任意两条 >40 字且相似度 >=0.8）
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i][2], ts[j][2]
                if len(a) > 40 and len(b) > 40:
                    r = SequenceMatcher(None, a, b).ratio()
                    if r >= 0.8:
                        d3 += 1
        # D4 利贞长议论
        for sp, ty, tx in ts:
            if sp == "利贞" and len(tx) > 120:
                d4 += 1
        # D5 利贞串味
        for sp, ty, tx in ts:
            if sp == "利贞" and LIZHEN_HABITS.search(tx):
                d5 += 1
        if d1 or d2 or d3 or d4 or d5:
            flagged.append((head, d1, d2, d3, d4, d5))
            totals["D1"] += d1
            totals["D2"] += d2
            totals["D3"] += d3
            totals["D4"] += d4
            totals["D5"] += d5
    print("文件 %s，块数 %d" % (os.path.basename(path), len(blocks)))
    print("缺陷合计：D1同人连发=%d D2无问之答=%d D3近重复=%d D4利贞长议论=%d D5利贞串味=%d"
          % (totals["D1"], totals["D2"], totals["D3"], totals["D4"], totals["D5"]))
    print("涉及块数 %d / %d" % (len(flagged), len(blocks)))
    print()
    print("%-28s %4s %4s %4s %4s %4s" % ("块", "D1", "D2", "D3", "D4", "D5"))
    for head, *ds in flagged:
        print("%-28s %4d %4d %4d %4d %4d" % (head[:28], *ds))
    clean = [b.splitlines()[0][3:].strip() for b in blocks
             if b.splitlines()[0][3:].strip() not in {h for h, *_ in flagged}]
    print()
    print("未触发任何缺陷指标的块 %d 个：%s" % (len(clean), "、".join(clean) if clean else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
