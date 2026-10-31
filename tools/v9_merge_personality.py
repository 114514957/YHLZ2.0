#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把「个性」生成批次合并成正式素材，并做最后一道质检。

要解决的四件事：
  ① **块名撞车**：每批都从 `性-1` 开始，合并后必须重编号成 `性-p0001…`
  ② **近重复**：同一场景生成了 7 条，难免撞；按元亨台词的字符集 Jaccard 去重
  ③ **门禁**：FAIL 一律不收
  ④ **对账**：确认"不叛逆、不口是心非"——统计每块元亨是"反对/同意/中性/追问"哪一类，
     并检查是否过度集中在某一种（那就又成模子了）

用法：
    python tools/v9_merge_personality.py --dry-run
    python tools/v9_merge_personality.py
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import re
import shutil
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

SRC_GLOB = "docs/素材/_草稿/个性生成_*.md"
OUT = "docs/素材/个性样本.md"

# 立场分类（用于对账：不能全是"反对"，也不能全是"同意"）
AGREE = re.compile(r"行[，。！]|可以|好[，。！]|那就|听你的|你说得对|我陪你|我同意|没问题|按你说的")
DISAGREE = re.compile(r"够什么|不行|不对|不猜|不够|别|凭什么|我不|才不|没必要|不同意|收回|错")
ASK = re.compile(r"[？?]|我想先知道|你说.{0,6}按什么|怎么算|哪来的")


def stance(ys: list[str]) -> str:
    j = "".join(ys)
    if ASK.search(j) and not DISAGREE.search(j) and not AGREE.search(j):
        return "追问"
    if DISAGREE.search(j) and AGREE.search(j):
        return "先否后允"
    if DISAGREE.search(j):
        return "反对"
    if AGREE.search(j):
        return "同意"
    return "中性"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def jaccard(a: str, b: str) -> float:
    A = {a[i:i + 4] for i in range(max(0, len(a) - 3))}
    B = {b[i:i + 4] for i in range(max(0, len(b) - 3))}
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dup", type=float, default=0.80, help="4-gram Jaccard 阈值")
    a = ap.parse_args()

    files = sorted(glob.glob(SRC_GLOB))
    print("批次文件 %d 个" % len(files))
    raw = []
    for p in files:
        text = io.open(p, encoding="utf-8").read()
        for b in re.split(r"(?m)^##\s+", text)[1:]:
            blk = "## " + b.strip() + "\n"
            blk = re.sub(r"(?m)^\s*=+\s*$", "", blk).strip() + "\n"
            raw.append(blk)
    print("原始块 %d" % len(raw))

    # ① 门禁 + 提取
    good, gate_fail = [], Counter()
    for blk in raw:
        rr = G.check_block("x", blk, "general")
        if rr["status"] == "FAIL":
            for f in rr["fails"]:
                gate_fail[re.sub(r"×\d+", "", f).split(":")[0].strip()] += 1
            continue
        ys = [m.group(1).strip() for m in
              re.finditer(r"^###\s*元亨答\d+\s*\n(.+?)(?=\n###|\Z)", blk, re.M | re.S)]
        if not ys:
            gate_fail["无元亨答"] += 1
            continue
        good.append((blk, ys))
    print("过门禁 %d ｜门禁剔 %d：%s" % (len(good), sum(gate_fail.values()),
                                       dict(gate_fail.most_common(5))))

    # ② 近重复
    kept, dropped_dup = [], 0
    sigs: list[str] = []
    for blk, ys in good:
        s = norm("".join(ys))
        if any(jaccard(s, t) >= a.dup for t in sigs):
            dropped_dup += 1
            continue
        sigs.append(s)
        kept.append((blk, ys))
    print("去重后 %d（剔 %d）" % (len(kept), dropped_dup))

    # ③ 立场分布对账
    st = Counter(stance(ys) for _, ys in kept)
    print("立场分布：%s" % dict(st))
    n = len(kept)
    if n:
        worst = max(st.values()) / n
        if worst > 0.55:
            print("⚠ 某一类立场占 %.0f%%，偏高（会又成模子）" % (100 * worst))

    # ④ 重编号 + 写盘
    out_blocks = []
    for i, (blk, ys) in enumerate(kept, 1):
        lines = blk.split("\n")
        lines[0] = "## 性-p%05d" % i
        out_blocks.append("\n".join(lines).rstrip() + "\n")

    head = ("# 元亨个性样本（%d 块）\n\n"
            "> 老爹 2026-10-21：「**元亨要的是个性，不是叛逆，不然出来一个口是心非的**」。\n"
            "> 与「教样本」的分工：教样本治毛病（被纠正就改），本样本长性格（她本来就有坐标系）。\n"
            "> 生成器 `tools/v9_gen_personality.py`；12 类 × 25 场景；合并器 `tools/v9_merge_personality.py`。\n"
            "> 每块过门禁 general 档；4-gram Jaccard ≥ %.2f 视为近重复剔除。\n"
            "> 立场分布（对账用，防止又成模子）：%s\n\n"
            % (len(out_blocks), a.dup,
               "｜".join("%s %d" % (k, v) for k, v in st.most_common())))

    if a.dry_run:
        print("\n抽样 3 块：")
        for b in out_blocks[:3]:
            print(b[:300])
        return 0

    if os.path.exists(OUT):
        bak = OUT.replace(".md", "_合并前.md")
        shutil.copy2(OUT, bak)
        print("旧文件已备份 -> %s" % os.path.basename(bak))
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(head)
        for b in out_blocks:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写 -> %s（%d 块）" % (OUT, len(out_blocks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
