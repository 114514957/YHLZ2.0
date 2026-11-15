# -*- coding: utf-8 -*-
"""数一数我们到底跑过几次 SFT，并用二项分布估 56 题的分数量化噪声。"""
from __future__ import annotations

import math
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 本机 eval56 记录 + 台账里记过的分数（56 题）
RUNS = [
    ("v3", 21, "gemma LoRA, 3ep"),
    ("v9t5", 25, "gemma LoRA, 3ep"),
    ("v9t6", 42, "gemma LoRA, 1ep"),
    ("v9t7", 45, "gemma LoRA, 1ep"),
    ("v9t8", 42, "gemma LoRA, 1ep"),
    ("v9t10", 48, "gemma LoRA, 1ep"),
    ("v9f1", None, "gemma 全参"),
    ("v10u", 48, "gemma LoRA, 1ep"),
    ("v11", 44, "gemma LoRA, 1ep, 数据×2.2"),
    ("stylepatch4", 46, "dpo2 上加 SFT 补丁"),
    ("v9t10-dpo2", 49, "DPO"),
    ("qwen v9t 全参", 29, "qwen3-4B 全参"),
    ("qwen v9t2", 32, "qwen3-4B 全参"),
    ("qwen v9t3", 30, "qwen3-4B 全参"),
    ("qwen v9t4", 32, "qwen3-4B 全参"),
]

print("我们跑过的、有 56 题分数的版本：%d 个" % len([r for r in RUNS if r[1] is not None]))
print("其中 gemma LoRA 同代可比的：%d 个" % len(
    [r for r in RUNS if r[1] is not None and "gemma LoRA" in r[2]]))
print()
for name, s, note in RUNS:
    print("  %-14s %-4s %s" % (name, s if s is not None else "—", note))

# 噪声估计：n=56，p 取观测到的水平，二项分布标准差
print("\n=== 56 题的分数量化噪声 ===")
for p in (0.75, 0.80, 0.85, 0.88):
    se_items = math.sqrt(p * (1 - p) * 56)
    print("  真实通过率 %.0f%% → 标准差 %.2f 题（约 %.1f 分），1σ 区间 ±%.1f 分"
          % (p * 100, se_items, se_items, se_items))

print("\n结论：1 题 = 1.79 分。我们历史上的分数差（42/45/48）大多在 ±3 分内。")
