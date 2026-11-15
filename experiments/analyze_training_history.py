# -*- coding: utf-8 -*-
"""把历史训练全部翻出来比对：超参表 + 逐 step 曲线 + 公式 + 问题定位。

数据源（都是本机真实文件，不是回忆）：
  · 配置：dist/retrain_pkg_*/config/*.json（16 份）
  · 逐 step：models/lora/*/train_log.csv（v9t7 / v9t8 / v9t10 / v11 / stylepatch4）
  · 摘要：同目录 train_summary.json
产出：
  · docs/研究/训练曲线_20261114.md
  · docs/研究/训练曲线/*.png（4 张）
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUTDIR = os.path.join(ROOT, "docs", "研究", "训练曲线")
os.makedirs(OUTDIR, exist_ok=True)

# 已评过的版本 → 56 题得分（judge v6）
SCORES = {"v9t7": 45, "v9t8": 42, "v9t10": 48, "v11": 44, "stylepatch4": None}
DISPLAY = {"v9t7": "v9t7", "v9t8": "v9t8", "v9t10": "v9t10",
           "v11": "v11", "stylepatch4": "stylepatch4(dpo2+)", "v9f1full": "v9f1 全量",
           "v9t11lora": "v9t11", "v9t9lora": "v9t9", "v9t6lora": "v9t6", "v9t5lora": "v9t5",
           "v10u": "v10u", "v9t2t": "v9t2", "v9t3t": "v9t3", "v9t4t": "v9t4"}

# ---------- 1) 超参表 ----------
rows = []
for p in sorted(glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_*", "config", "*.json"))):
    try:
        c = json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    tag = os.path.basename(p).replace("finetune.", "").replace(".json", "")
    tm = str(c.get("target_modules") or "")
    n_mod = len([k for k in ("q_proj", "k_proj", "v_proj", "o_proj",
                             "gate_proj", "up_proj", "down_proj") if k in tm])
    rows.append({
        "pkg": os.path.basename(os.path.dirname(os.path.dirname(p))),
        "tag": tag,
        "lr": c.get("lr"),
        "epochs": c.get("epochs"),
        "batch": c.get("batch_size"),
        "accum": c.get("grad_accum"),
        "eff_batch": (c.get("batch_size") or 1) * (c.get("grad_accum") or 1),
        "seq": c.get("max_seq_len"),
        "r": c.get("lora_r"), "alpha": c.get("lora_alpha"),
        "mods": n_mod,
        "4bit": c.get("load_in_4bit"),
        "full": c.get("full_finetune"),
        "mask": c.get("mask_prompt"),
        "warmup": c.get("warmup_ratio"),
        "sched": c.get("lr_scheduler_type"),
        "optim": c.get("optim"),
    })
df_cfg = pd.DataFrame(rows)
df_cfg.to_csv(os.path.join(OUTDIR, "hyperparams.csv"), index=False, encoding="utf-8-sig")

# ---------- 2) 逐 step 曲线 ----------
curves = {}
for p in sorted(glob.glob(os.path.join(ROOT, "models", "lora", "*", "train_log.csv"))):
    name = os.path.basename(os.path.dirname(p))
    short = (name.replace("yuanheng-", "").replace("v9-gemma-", "")
             .replace("yuanheng", "").strip("-"))
    try:
        d = pd.read_csv(p)
    except Exception:  # noqa: BLE001
        continue
    if "loss" not in d.columns:
        continue
    d = d[d["loss"].notna()].copy()
    if d.empty:
        continue
    if "step" not in d.columns:
        d["step"] = np.arange(1, len(d) + 1)
    d["short"] = short
    curves[short] = d
    print("曲线 %-14s %4d 点（step %d..%d）" % (short, len(d), d["step"].min(), d["step"].max()))

# ---------- 3) 汇总统计 ----------
stats = []
for k, d in curves.items():
    loss = d["loss"].astype(float)
    n = len(loss)
    window = max(3, n // 20)
    start = float(loss.head(window).mean())
    end = float(loss.tail(window).mean())
    s = {"run": k, "points": n,
         "steps": int(d["step"].max()),
         "loss_start": round(start, 3), "loss_end": round(end, 3),
         "loss_min": round(float(loss.min()), 3),
         "drop_pct": round(100 * (1 - end / start), 1) if start > 0 else None}
    if "learning_rate" in d.columns:
        s["lr_peak"] = float(d["learning_rate"].astype(float).max())
        s["lr_last"] = float(d["learning_rate"].astype(float).iloc[-1])
    if "grad_norm" in d.columns:
        gn = d["grad_norm"].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(gn):
            s["gn_mean"] = round(float(gn.mean()), 2)
            s["gn_p95"] = round(float(np.percentile(gn, 95)), 2)
            s["gn_max"] = round(float(gn.max()), 2)
    if "eval_loss" in d.columns:
        ev = d["eval_loss"].astype(float).dropna()
        if len(ev):
            s["eval_first"] = round(float(ev.iloc[0]), 3)
            s["eval_last"] = round(float(ev.iloc[-1]), 3)
    s["score56"] = SCORES.get(k)
    stats.append(s)
df_stats = pd.DataFrame(stats).sort_values("run")
df_stats.to_csv(os.path.join(OUTDIR, "run_stats.csv"), index=False, encoding="utf-8-sig")

# ---------- 4) 图 ----------
plt.rcParams.update({"figure.dpi": 130, "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.3})
COLORS = plt.cm.tab10.colors


def smooth(y, k=15):
    if len(y) < k:
        return y
    return np.convolve(y, np.ones(k) / k, mode="valid")


# 图1：loss vs step（各自步数）
fig, ax = plt.subplots(figsize=(8, 4.4))
for i, (k, d) in enumerate(curves.items()):
    y = d["loss"].astype(float).values
    x = np.arange(len(y))
    ax.plot(x, y, color=COLORS[i % 10], lw=0.6, alpha=0.35)
    ys = smooth(y)
    ax.plot(np.arange(len(ys)), ys, color=COLORS[i % 10], lw=1.8,
            label="%s (%d steps, %s)" % (k, len(y), SCORES.get(k, "-")))
ax.set_xlabel("step")
ax.set_ylabel("train loss")
ax.set_title("Loss vs step (thin=raw, thick=smoothed)")
ax.legend(fontsize=7, loc="upper right")
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "loss_vs_step.png"))
plt.close(fig)

# 图2：loss vs 训练进度（归一化，可比）
fig, ax = plt.subplots(figsize=(8, 4.4))
for i, (k, d) in enumerate(curves.items()):
    y = d["loss"].astype(float).values
    xs = np.linspace(0, 1, len(y))
    ax.plot(xs, y, color=COLORS[i % 10], lw=0.5, alpha=0.25)
    ys = smooth(y)
    ax.plot(np.linspace(0, 1, len(ys)), ys, color=COLORS[i % 10], lw=1.8,
            label="%s  drop=%s%%" % (k, df_stats.set_index("run").loc[k, "drop_pct"]))
ax.set_xlabel("training progress (0-1)")
ax.set_ylabel("train loss")
ax.set_title("Loss vs progress (comparable across runs)")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "loss_vs_progress.png"))
plt.close(fig)

# 图3：lr 曲线（公式可视化）
fig, ax = plt.subplots(figsize=(8, 3.6))
for i, (k, d) in enumerate(curves.items()):
    if "learning_rate" not in d.columns:
        continue
    lr = d["learning_rate"].astype(float).values
    ax.plot(np.linspace(0, 1, len(lr)), lr, color=COLORS[i % 10], lw=1.6, label=k)
ax.set_xlabel("training progress (0-1)")
ax.set_ylabel("learning rate")
ax.set_title("LR schedule actually used (from trainer log)")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "lr_curves.png"))
plt.close(fig)

# 图4：grad_norm vs 进度（对数轴）
fig, ax = plt.subplots(figsize=(8, 4.0))
for i, (k, d) in enumerate(curves.items()):
    if "grad_norm" not in d.columns:
        continue
    gn = d["grad_norm"].astype(float).replace([np.inf, -np.inf], np.nan)
    ok = gn.notna()
    if not ok.any():
        continue
    xs = np.linspace(0, 1, len(gn))[ok.values]
    ax.plot(xs, gn[ok].values, color=COLORS[i % 10], lw=0.8, alpha=0.6)
    ys = smooth(gn[ok].values, 9)
    ax.plot(np.linspace(0, 1, len(ys)), ys, color=COLORS[i % 10], lw=1.8, label=k)
ax.set_yscale("log")
ax.set_xlabel("training progress (0-1)")
ax.set_ylabel("grad_norm (log)")
ax.set_title("Gradient norm vs progress")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "grad_norm.png"))
plt.close(fig)

print("\n图已写：%s" % OUTDIR)
print(df_stats.to_string(index=False))
print("\n超参表：%d 行" % len(df_cfg))
