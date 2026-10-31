#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给元亨台词补「老爹」称呼（老爹 2026-10-21：「补，把一些已有的内容主人公或者提问者改成老爹就行」）。

现状：2,040 块里只有 141 块（6.9%）的元亨台词提到"老爹"，关系感偏淡。
做法：把元亨台词里**指老爹的那个「你」**换成「老爹」。
  · **只换约一半**（不到全部）—— 全换会变成新模子，称呼率冲到 84% 反而假
  · 每块**最多换 1 处**，且只换第一处
  · 只动**元亨**的台词，老爹的话一字不动
  · 跳过「你们」，跳过引号内引用，跳过句中的"你看/你说"这类插入语（换进去会别扭）

用法：
    python tools/v9_add_call.py --dry-run
    python tools/v9_add_call.py --ratio 0.5
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

P = "docs/素材/个性样本.md"
# 这些「你」换进去会别扭：你们 / 你俩 / 你看（插入语）/ 你说（插入语开头）
SKIP_PREFIX = ("你们", "你俩", "你我")
SKIP_AFTER = ("看", "说", "想", "瞧", "听")   # 你看/你说/你想…作插入语时不动


def pick_you(text: str) -> int:
    """返回可替换的「你」的下标，找不到返回 -1。

    2026-10-21 收紧：**只换位于小句开头**的「你」（前面是行首或标点）。
    原因是「看**你**图什么」→「看**老爹**图什么」读起来别扭——那种「你」是宾语，
    换进去不通。句首的「你」才是称呼对象，换成「老爹」才自然。
    """
    spans = []
    for m in re.finditer(r"[「『\"“][^」』\"”]{0,40}[」』\"”]", text):
        spans.append((m.start(), m.end()))

    def in_quote(i: int) -> bool:
        return any(a <= i < b for a, b in spans)

    START = "。！？，、；：…—～ \t"
    for i, ch in enumerate(text):
        if ch != "你":
            continue
        if i > 0 and text[i - 1] not in START:
            continue                      # 不是小句开头，跳过
        if in_quote(i):
            continue
        if any(text[i:i + 2].startswith(p) for p in SKIP_PREFIX):
            continue
        if text[i + 1:i + 2] in SKIP_AFTER:
            continue
        return i
    return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.5, help="换多少比例的可换块")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = io.open(P, encoding="utf-8").read()
    m = re.search(r"(?ms)^(.*?)(?=^## )", text)
    head = m.group(1) if m else ""
    blks = re.split(r"(?m)^##\s+", text)[1:]
    print("总 %d 块｜目标替换比例 %.0f%%" % (len(blks), a.ratio * 100))

    out, changed, skip_has, skip_noyou, gate_drop = [], 0, 0, 0, 0
    eligible = 0
    for idx, b in enumerate(blks):
        lines = b.split("\n")
        # 先看元亨台词
        role, ys_idx = None, []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("### "):
                role = "元亨" if "答" in s else "老爹"
            elif s and not s.startswith(("-", "#")) and role == "元亨":
                ys_idx.append(i)
                role = None
        ytext = "".join(lines[i].strip() for i in ys_idx)
        if "老爹" in ytext:
            skip_has += 1
            out.append("## " + b)
            continue
        pos = -1
        for i in ys_idx:
            pos = pick_you(lines[i])
            if pos >= 0:
                target = i
                break
        if pos < 0:
            skip_noyou += 1
            out.append("## " + b)
            continue
        eligible += 1
        # 用 (idx * 2654435761) % 1000 做确定性散列，保证可复现
        take = ((idx * 2654435761) % 1000) / 1000.0 < a.ratio
        if not take:
            out.append("## " + b)
            continue
        ln = lines[target]
        lines[target] = ln[:pos] + "老爹" + ln[pos + 1:]
        blk = "## " + "\n".join(lines)
        rr = G.check_block("x", blk, "general")
        if rr["status"] == "FAIL":
            gate_drop += 1
            out.append("## " + b)
            continue
        out.append(blk)
        changed += 1

    total = len(out)
    with_call = 0
    for b in out:
        role = None
        for ln in b.split("\n"):
            s = ln.strip()
            if s.startswith("### "):
                role = "元亨" if "答" in s else "老爹"
            elif s and not s.startswith(("-", "#")) and role == "元亨":
                if "老爹" in s:
                    with_call += 1
                    break
                role = None
    print("可换 %d 块｜实换 %d 块（门禁挡回 %d）｜已有称呼跳过 %d｜无「你」跳过 %d"
          % (eligible, changed, gate_drop, skip_has, skip_noyou))
    print("称呼率：%.1f%% → **%.1f%%**"
          % (100.0 * skip_has / total, 100.0 * with_call / total))

    if a.dry_run:
        print("\n替换样例：")
        n = 0
        for b0, b1 in zip(blks, out):
            if b0 != b1:
                ys0 = [l.strip() for l in b0.split("\n")
                       if l.strip() and not l.startswith(("-", "#", "###"))]
                ys1 = [l.strip() for l in b1.split("\n")
                       if l.strip() and not l.startswith(("-", "#", "###"))]
                for x, y in zip(ys0, ys1):
                    if x != y:
                        print("   前：%s" % x[:64])
                        print("   后：%s" % y[:64])
                n += 1
                if n >= 4:
                    break
        return 0

    bak = P.replace(".md", "_补称呼前.md")
    shutil.copy2(P, bak)
    new_head = head.replace(
        "> 每块过门禁 general 档",
        "> 2026-10-21 补称呼：把元亨台词里指老爹的「你」换成「老爹」，**只换约 %.0f%%**"
        "（全换会成新模子）；改后称呼率 %.1f%%。\n> 每块过门禁 general 档"
        % (a.ratio * 100, 100.0 * with_call / total))
    with io.open(P, "w", encoding="utf-8") as fh:
        fh.write(new_head)
        for b in out:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写回 %s（备份 %s）" % (P, os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
