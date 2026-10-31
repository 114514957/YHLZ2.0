#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""L01 扩写批独立复核（只读）。

不采信交付说明，直接对文件做机械复核：
块数/编号连续性/元数据齐全/expansion_of 溯源/轮数/元亨条数与占比/最长轮/自称种类/
禁项自检/复读自检/（可选）指定源块的修复确认。

用法：python tools/v9_l01_verify.py [文件路径]
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(PROJECT_ROOT, "docs", "素材", "_草稿", "L01_扩写30块_对话1至30_20261013.md")

TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
META = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.M)
BAD_CHARS = {"括号": r"[（(][^）)]{0,20}[）)]", "星号": r"\*", "分号": r"；", "冒号": r"：",
             "列表行": r"(?m)^[ \t]*([-*•]|\d+[.、)])\s"}
BAD_WORDS = {"客服腔": r"为您|建议您|建议你|我可以帮|请问|祝您",
             "模板腔": r"首先|其次|总之|综上所述|总的来说|需要注意的是|值得注意的是|让我来",
             "报告腔": r"已完成|任务完成|处理完成|已为您"}
SELF_REFS = ["我", "咱", "本小姐", "老娘", "元亨"]
FILLERS = ["先说好", "我这边", "别指望", "后来我", "说句不客气", "理论上来说"]
REQUIRED_META = ["category", "subtype", "status", "emotion", "length_tier", "contract", "fiction"]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with io.open(path, "r", encoding="utf-8") as fh:
        text = fh.read().replace("\r\n", "\n")
    blocks = [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]
    print("文件: %s" % os.path.basename(path))
    print("块数: %d" % len(blocks))

    nums, problems = [], []
    rounds_all, yh_counts, self_ref_sets, ultra, endings = [], [], [], [], Counter()
    for blk in blocks:
        head = blk.splitlines()[0][3:].strip()
        m = re.match(r"故事-(\d+)｜", head)
        nums.append(int(m.group(1)) if m else -1)
        meta = {k.lower(): v for k, v in META.findall(blk)}
        miss = [k for k in REQUIRED_META if not meta.get(k)]
        if miss:
            problems.append("%s 缺元数据 %s" % (head, miss))
        exp = meta.get("expansion_of", "")
        if not re.match(r"^对话-\d+$", exp):
            problems.append("%s expansion_of 异常: %r" % (head, exp))
        ts = []
        ms = list(TURN.finditer(blk))
        for i, mm in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            ts.append((mm.group(1).strip(), mm.group(2), int(mm.group(3)), blk[mm.end():end].strip()))
        # 轮号连续
        seq = [t[2] for t in ts]
        if seq != list(range(1, len(seq) + 1)):
            problems.append("%s 轮号不连续: %s" % (head, seq))
        yh = [t for t in ts if t[0] == "元亨"]
        yh_text = "\n".join(t[3] for t in yh)
        joined = "\n".join(t[3] for t in ts)
        rounds_all.append(len(ts))
        yh_counts.append(len(yh))
        kinds = [k for k in SELF_REFS if k in yh_text]
        if len(kinds) < 2:
            problems.append("%s 自称少于 2 种: %s" % (head, kinds))
        self_ref_sets.append(tuple(kinds))
        mx = max((len(t[3]) for t in ts), default=0)
        ultra.append(mx)
        if mx < 400:
            problems.append("%s 超长句 %d <400" % (head, mx))
        for tag, pat in BAD_CHARS.items():
            n = len(re.findall(pat, joined))
            if n:
                problems.append("%s 禁符 %s ×%d" % (head, tag, n))
        for tag, pat in BAD_WORDS.items():
            n = len(re.findall(pat, joined))
            if n:
                problems.append("%s 禁词 %s ×%d" % (head, tag, n))
        if "理论上来说" in yh_text:
            problems.append("%s 元亨用了「理论上来说」" % head)
        for f in FILLERS:
            n = joined.count(f)
            if n >= 2:
                problems.append("%s 填充语撞车 %s ×%d" % (head, f, n))
        for t in yh:
            tail = t[3].rstrip()
            if tail.endswith(("？", "?")):
                endings["问"] += 1
            elif tail.endswith(("！", "!")):
                endings["叹"] += 1
            elif tail.endswith(("…", "。")):
                endings["陈述"] += 1
            else:
                endings["短/停顿"] += 1
        # 元亨自我整段复读检查（同一块内两条元亨发言重合度）
        for i in range(len(yh)):
            for j in range(i + 1, len(yh)):
                a, b = yh[i][3], yh[j][3]
                if len(a) > 60 and len(b) > 60 and (a in b or b in a):
                    problems.append("%s 元亨答%d/答%d 存在整段包含复读" % (head, i + 1, j + 1))

    # 编号
    if nums != list(range(201, 201 + len(blocks))):
        problems.append("块编号不连续或不从 201 起: %s" % nums[:6] + "...")
    # 源覆盖
    srcs = sorted(int(re.search(r"对话-(\d+)", m).group(1))
                  for m in re.findall(r"expansion_of: (对话-\d+)", text))
    missing = [n for n in range(1, 31) if n not in srcs]
    dup = [n for n, c in Counter(srcs).items() if c > 1]

    print("编号: %d-%d 连续=%s" % (min(nums), max(nums), nums == list(range(201, 201 + len(blocks)))))
    print("源覆盖: 对话1-30 缺=%s 重复=%s" % (missing or "无", dup or "无"))
    print("轮数: 最少 %d / 最多 %d / 均 %.1f" % (min(rounds_all), max(rounds_all), sum(rounds_all) / len(rounds_all)))
    print("元亨条数: 最少 %d / 最多 %d / 均 %.1f" % (min(yh_counts), max(yh_counts), sum(yh_counts) / len(yh_counts)))
    print("元亨占比: 最低 %.0f%% / 均 %.0f%%"
          % (100 * min(y / r for y, r in zip(yh_counts, rounds_all)),
             100 * sum(yh_counts) / sum(rounds_all)))
    print("超长轮: 最少 %d / 最多 %d（要求 ≥400）" % (min(ultra), max(ultra)))
    print("收尾分布(元亨): %s" % dict(endings))
    tot = sum(endings.values())
    if tot:
        print("收尾最高占比: %.0f%%" % (100 * max(endings.values()) / tot))
    print()
    if problems:
        print("发现问题 %d 条:" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1
    print("机械复核：全部通过，未发现问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
