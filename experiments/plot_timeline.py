# -*- coding: utf-8 -*-
"""出图 + 写报告：全时间线 v3→v11 的分数 / epoch / lr / 数据量 / loss 关系。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "docs", "研究", "训练曲线")
os.makedirs(OUT, exist_ok=True)

# 版本, 基座, 方法, lr, epochs, 有效batch, 数据量, 56题, loss_drop%
RUNS = [
    ("v3",        "gemma-E4B", "LoRA",  2.0e-4, 3, 16, None,  21, None),
    ("v9t5",      "gemma-E4B", "LoRA",  2.0e-4, 3,  8, 6116,  25, None),
    ("v9t6",      "gemma-E4B", "LoRA",  2.0e-4, 1,  8, 6155,  42, None),
    ("v9t7",      "gemma-E4B", "LoRA",  2.0e-4, 1,  8, 5659,  45, 46.2),
    ("v9t8",      "gemma-E4B", "LoRA",  2.0e-4, 1,  8, 5931,  42, 41.4),
    ("v9t10",     "gemma-E4B", "LoRA",  2.0e-4, 1,  8, 5931,  48, 42.7),
    ("v9t10-dpo2", "gemma-E4B", "DPO",  None,  None, None, None, 49, None),
    ("v11",       "gemma-E4B", "LoRA",  1.5e-4, 1,  8, 13189, 44, 63.0),
    ("stylepatch", "dpo2+补丁", "SFT补丁", 3.0e-5, 2, 8, 318,  46, 47.6),
    ("qwen-v9t",  "qwen3-4B",  "全参",  2.0e-5, 1, 16, None,  29, None),
]

plt.rcParams.update({"figure.dpi": 140, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3})

names = [r[0] for r in RUNS]
scores = [r[7] for r in RUNS]

# 图 A：分数时间线（按版本顺序），epoch 标在点上
fig, ax = plt.subplots(figsize=(9, 4.2))
x = np.arange(len(RUNS))
colors = ["#888" if r[7] < 40 else ("#2b8a3e" if r[7] >= 45 else "#c92a2a")
          for r in RUNS]
bars = ax.bar(x, scores, color=colors, alpha=0.85)
for i, r in enumerate(RUNS):
    ax.text(i, r[7] + 0.6, "%d" % r[7], ha="center", fontsize=8)
    ax.text(i, 1.2, "ep=%s" % (r[4] if r[4] else "-"), ha="center",
            fontsize=7, color="white", rotation=90)
ax.set_xticks(x)
ax.set_xticklabels([n.replace("v9t", "t").replace("-dpo2", "+DPO") for n in names],
                   fontsize=7, rotation=20)
ax.axhline(49, ls="--", lw=0.8, color="#1971c2")
ax.text(len(RUNS) - 0.4, 49.4, "best 49", fontsize=7, color="#1971c2", ha="right")
ax.set_ylabel("56-item score")
ax.set_title("Score timeline (v3 -> v11). grey<40, red 40-44, green>=45")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "score_timeline.png"))
plt.close(fig)

# 图 B：epoch 与分数（3 epoch 的悬崖）
fig, ax = plt.subplots(figsize=(6.2, 4.0))
for i, r in enumerate(RUNS):
    if r[4] is None:
        continue
    ax.scatter(r[4], r[7], s=90, color=colors[i], zorder=3)
    ax.annotate(r[0], (r[4], r[7]), textcoords="offset points", xytext=(6, -3),
                fontsize=7)
ax.set_xlabel("epochs")
ax.set_ylabel("56-item score")
ax.set_title("Epochs vs score: 3 epochs collapses (v3/v9t5), 1 epoch works")
ax.axvspan(2.5, 3.5, color="#ffd43b", alpha=0.15)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "epochs_vs_score.png"))
plt.close(fig)

# 图 C：loss 降幅 与 分数（有没有关系）
fig, ax = plt.subplots(figsize=(6.2, 4.0))
pts = [(r[8], r[7], r[0]) for r in RUNS if r[8] is not None]
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
ax.scatter(xs, ys, s=90, color="#1971c2", zorder=3)
for xx, yy, nn in pts:
    ax.annotate(nn, (xx, yy), textcoords="offset points", xytext=(6, -3), fontsize=7)
if len(xs) > 1:
    z = np.polyfit(xs, ys, 1)
    xr = np.linspace(min(xs), max(xs), 10)
    ax.plot(xr, np.polyval(z, xr), ls="--", lw=1, color="#c92a2a")
    corr = float(np.corrcoef(xs, ys)[0, 1])
    ax.set_title("Loss drop vs score (corr=%.2f) -- lower loss != better persona" % corr)
else:
    ax.set_title("Loss drop vs score")
ax.set_xlabel("train loss drop %")
ax.set_ylabel("56-item score")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "lossdrop_vs_score.png"))
plt.close(fig)

print("图：score_timeline.png / epochs_vs_score.png / lossdrop_vs_score.png")
if len(xs) > 1:
    print("loss_drop 与 分数 相关系数 = %.2f" % float(np.corrcoef(xs, ys)[0, 1]))
