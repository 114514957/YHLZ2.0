# -*- coding: utf-8 -*-
"""算账：每版训练花了多少钱、每提升一分值多少、以及卡型怎么选。

单价来自老爹 2026-11-11 截图（AutoDL 按量计费）：
  A800-80GB   ¥5.59/时（原价 5.88）   ← 我们一直用的
  RTX 6000D 84GB  ¥6.46/时（原价 6.80）
  MTT S4000 48GB×2 ¥3.72/时（原价 3.92）← MUSA 生态，CUDA 代码跑不了
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "docs", "研究", "训练成本对账_20261111.json")
PRICE = 5.59

# 版本 / 秒 / 56题得分（不得分为 None）
RUNS = [
    ("v9t6", None, 46),
    ("v9t7", None, 45),
    ("v9t8", 2222.8, 42),
    ("v9t10", 2639.8, 48),
    ("v9t10-dpo(v1)", 290.6, 45),
    ("v9t10-dpo2", 224.4, 45),
    ("v9f1 全量", 3073.8, None),
]
# 非训练的 GPU 时间（分钟）：S0 诊断、S2 三组实验、若干次评测
EXTRA = [
    ("S0 秩诊断", 2.0), ("S2 λ扫描", 7.9), ("S2 A/B", 13.1),
    ("S2 A/B 加扫", 7.0), ("DPO 前后评测 ×4", 6.0), ("全量评测/风格 ×3", 5.0),
]

rows = []
for name, sec, score in RUNS:
    if sec is None:
        rows.append({"版本": name, "训练分钟": None, "成本": None, "56题": score})
        continue
    minutes = sec / 60
    cost = minutes / 60 * PRICE
    rows.append({"版本": name, "训练分钟": round(minutes, 1),
                 "成本": round(cost, 2), "56题": score})

print("=" * 62)
print("%-16s %10s %10s %8s %12s" % ("版本", "训练分钟", "成本(元)", "56题", "每分成本"))
for r in rows:
    per = ("%.2f" % (r["成本"] / r["56题"])) if (r["成本"] and r["56题"]) else "—"
    print("%-16s %10s %10s %8s %12s"
          % (r["版本"], r["训练分钟"] or "?", r["成本"] or "?", r["56题"] or "—", per))

train_cost = sum(r["成本"] for r in rows if r["成本"])
extra_min = sum(m for _n, m in EXTRA)
extra_cost = extra_min / 60 * PRICE
print("\n训练合计：%.2f 元" % train_cost)
print("实验/评测（非训练）合计：%.1f 分钟 = %.2f 元" % (extra_min, extra_cost))
print("本阶段 AI 计算总花费（不含下载/调试闲置）：**%.2f 元**" % (train_cost + extra_cost))

print("\n=== 边际收益 ===")
print("v9t8(42) → v9t10(48)：+6 分，花 %.2f 元 → **%.2f 元/分**"
      % (4.10, 4.10 / 6))
print("v9t10(48) → dpo2+两条示例(49)：+1 分，花 %.2f 元（DPO 0.35 + 改提示词 0）→ **%.2f 元/分**"
      % (0.35, 0.35))
print("纯改提示词那 1 分：**0 元**（只花了我的时间）")

print("\n=== 卡型选择 ===")
CARDS = [("A800-80GB", 5.59, "CUDA，我们全部脚本直接跑", True),
         ("RTX 6000D 84GB", 6.46, "CUDA，显存更大但贵 16%", True),
         ("MTT S4000 48GB×2", 3.72, "MUSA 生态，torch/peft/bnb 要重编或换栈", False)]
for name, price, note, usable in CARDS:
    print("   %-20s ¥%.2f/时  %s  %s"
          % (name, price, "✅可用" if usable else "❌要移植", note))
print("\n结论：**A800 ¥5.59/时 是三者里唯一「便宜且能直接跑」的**。")
print("      MTT 便宜 33%，但我们的训练栈是 CUDA + bitsandbytes，移植成本远高于省下的钱。")

# 全量微调的账
full_min = 3073.8 / 60
print("\n=== 全量微调（v9f1）特别说明 ===")
print("  935 步 / %.1f 分钟 / %.2f 元 —— 是 LoRA（v9t10，44 分钟，4.10 元）的 1.16 倍时间。" % (full_min, full_min / 60 * PRICE))
print("  但它产出 15.88GB 模型（LoRA 只有 139.6MB），**下载/转存成本高两个数量级**：")
down_min = 15882 / 3.2 / 60      # 15882 MB ÷ 12 路实测 3.2MB/s
print("  按 12 路 3.2MB/s 拉回本地要 %.0f 分钟；每次换版本都要重来。" % down_min)
print("  → 全量的隐性成本不在卡上，在**分发**上。")

with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump({"price": PRICE, "rows": rows,
               "train_cost": round(train_cost, 2),
               "extra_cost": round(extra_cost, 2),
               "total": round(train_cost + extra_cost, 2),
               "cards": [{"name": n, "price": p, "usable": u} for n, p, _x, u in CARDS]},
              f, ensure_ascii=False, indent=1)
print("\n写出 %s" % OUT)
