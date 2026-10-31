#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材 token 聚合分析（只读）。

读 cache/v9_materials_preparation/20261013/token_measure.json，按"训练池"口径
汇总：真实 token 密度、每块监督 token、以及按 80k 段外推的曝光量。

用法：python tools/v9_token_summary.py [--target 80000]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(
    PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013", "token_measure.json"
)

# 池 → 文件映射（与盘点口径一致；长块单列）
POOLS = {
    "核心·对话样本": ["docs/素材/对话样本.md"],
    "核心·记忆v2": ["docs/素材/记忆样本_v2.md"],
    "核心·诚实边界": ["docs/素材/诚实边界样本.md"],
    "核心·安全拒绝": ["docs/素材/安全拒绝样本.md"],
    "核心·承认不确定": ["docs/素材/承认不确定样本.md"],
    "核心·真实对话": ["docs/素材/真实对话样本.md"],
    "核心·优质样本": ["docs/素材/优质样本.md"],
    "已改写·批次01": ["docs/素材/_修订/批次01_去IT味_对话-1至15_20261011.md"],
    "长块·S01首批": ["docs/素材/_草稿/S01_长块首批_续写扩写新写_20261012.md"],
    "长块·测试样本两集": ["docs/素材/_草稿/测试样本_新线两集_v0_20261011.md"],
}


def show(s: str) -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=80000)
    args = ap.parse_args()

    with io.open(SRC, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    by_path = {f["path"]: f for f in data["files"]}

    show("=" * 78)
    show("V9 素材 token 实测聚合（tokenizer = Gemma 4 E4B，%s）" % os.path.basename(data["tokenizer"]))
    show("=" * 78)
    show("%-18s %6s %11s %11s %9s %9s" % ("池", "块数", "整块token", "监督token", "监督/块", "tok/汉字"))
    rows = []
    for pool, files in POOLS.items():
        blocks = full = asst = 0
        for f in files:
            r = by_path.get(f)
            if not r:
                continue
            blocks += r["blocks"]
            full += r["total_full_tokens"]
            asst += r["total_assistant_tokens"]
        if not blocks:
            continue
        ratio = asst / full if full else 0
        rows.append((pool, blocks, full, asst, asst / blocks, ratio))
        show("%-18s %6d %11d %11d %9.1f %9.2f"
             % (pool, blocks, full, asst, asst / blocks, ratio))

    tb = sum(r[1] for r in rows)
    tf = sum(r[2] for r in rows)
    ta = sum(r[3] for r in rows)
    show("-" * 78)
    show("%-18s %6d %11d %11d %9.1f %9.2f" % ("合计（已解析）", tb, tf, ta, ta / tb, ta / tf))

    # 长块 vs 中短块密度对比
    longblocks = by_path.get("docs/素材/_草稿/S01_长块首批_续写扩写新写_20261012.md")
    longones = by_path.get("docs/素材/_草稿/测试样本_新线两集_v0_20261011.md")
    mid = by_path.get("docs/素材/对话样本.md")
    if longblocks and mid and longones:
        long_tok = (longblocks["total_assistant_tokens"] + longones["total_assistant_tokens"]) / (
            longblocks["blocks"] + longones["blocks"]
        )
        mid_tok = mid["avg_assistant_tokens_per_block"]
        show("")
        show("密度对比：长块 %.0f 监督token/块  vs  中短块（对话样本）%.0f  →  长块是 %.1fx"
             % (long_tok, mid_tok, long_tok / mid_tok if mid_tok else 0))

    # 80k 段外推
    show("")
    show("按 %d 段外推（假设池内密度与现有素材一致）：" % args.target)
    for pool, blocks, full, asst, per, _ in rows:
        pass
    # 用四池目标配额做外推（配额见 V9_八万段语料目标修订）
    quota = {
        "核心黄金池": (4000, 250),
        "说话与一般任务": (36000, 400),
        "工具与概念边界": (24000, 600),
        "上下文与多轮": (16000, 600),
    }
    total_tok = 0
    show("  %-16s %8s %14s %14s" % ("池", "配额", "假设监督/块", "监督token小计"))
    for pool, (q, per) in quota.items():
        sub = q * per
        total_tok += sub
        show("  %-16s %8d %14d %14d" % (pool, q, per, sub))
    show("  %-16s %8d %14s %14d" % ("合计", args.target, "-", total_tok))
    show("")
    exp = total_tok / 1_000_000
    show("曝光换算（assistant 监督 token）：1 遍 ≈ %.1fM；3 遍 ≈ %.1fM；5 遍 ≈ %.1fM；10 遍 ≈ %.1fM"
         % (exp, exp * 3, exp * 5, exp * 10))
    show("对照：现存量（已解析 %d 块）监督 token = %.2fM，只够 80k 目标的 %.1f%%"
         % (tb, ta / 1_000_000, 100.0 * ta / total_tok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
