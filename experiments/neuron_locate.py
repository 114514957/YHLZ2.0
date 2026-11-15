# -*- coding: utf-8 -*-
"""神经元定位（不需要 GPU）：
  ① 每层 down_proj 的第 j 列 = 第 j 个 FFN 神经元写回残差流的方向
  ② 与拒绝方向 v_L 的对齐度 |W[:, j] · v_L| → 谁在为"拒绝"出力
  ③ 与 LoRA 的实际改动 ‖ΔW[:, j]‖ 交叉 → 训练已经动了哪些神经元
输出：dist/neuron_report/{top_neurons.csv, summary.md}
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
import torch
from safetensors import safe_open

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "models", "llama-cuda", "src",
                                "llama.cpp-b10991", "gguf-py"))
from gguf import GGUFReader  # noqa: E402

BASE = os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it", "model.safetensors")
LORA = os.path.join(YH, "models", "lora", "yuanheng-v9t10-dpo2", "adapter_model.safetensors")
CVEC = os.path.join(YH, "llm_workbench", "steer", "cvec_refuse_mean.gguf")
OUT = os.path.join(YH, "dist", "neuron_report")
LAYERS = [12, 16, 20, 24, 28]
os.makedirs(OUT, exist_ok=True)

# ① 读方向
r = GGUFReader(CVEC)
dirs = {int(t.name.split(".")[1]): np.array(t.data[:], dtype=np.float32)
        for t in r.tensors}
print("方向层：%s" % sorted(dirs))

# ② LoRA 的 A/B（拿 down_proj 的增量）
adapter = {}
with safe_open(LORA, framework="pt", device="cpu") as f:
    for k in f.keys():
        if "lora_" in k:
            adapter[k] = f.get_tensor(k)
print("adapter 张量 %d 个｜样例 %s" % (len(adapter), list(adapter)[:2]))

rows = []
summary = {}
with safe_open(BASE, framework="pt", device="cpu") as f:
    for L in LAYERS:
        name = "model.language_model.layers.%d.mlp.down_proj.weight" % L
        W = f.get_tensor(name).float().numpy()          # [2560, 10240]
        v = dirs.get(L + 1)
        if v is None:
            v = dirs.get(L)
        if v is None:
            print("  L%d 没有方向，跳过" % L)
            continue
        proj = np.abs(W.T @ v)                           # [10240] 每神经元的对齐度
        wnorm = np.linalg.norm(W, axis=0)                # 每神经元的写出强度

        # LoRA 增量（若这一层被训过）
        ka = "base_model.model.model.language_model.layers.%d.mlp.down_proj.lora_A.weight" % L
        kb = "base_model.model.model.language_model.layers.%d.mlp.down_proj.lora_B.weight" % L
        dnorm = None
        if ka in adapter and kb in adapter:
            A = adapter[ka].float().numpy()              # [r, 10240]
            B = adapter[kb].float().numpy()              # [2560, r]
            dW = B @ A                                   # [2560, 10240]
            dnorm = np.linalg.norm(dW, axis=0)           # [10240]

        top = np.argsort(-proj)[:200]
        summary["L%d" % L] = {
            "proj_max": float(proj.max()), "proj_mean": float(proj.mean()),
            "top200_share": float(proj[top].sum() / proj.sum()),
            "corr_proj_vs_wnorm": float(np.corrcoef(proj, wnorm)[0, 1]),
        }
        if dnorm is not None:
            summary["L%d" % L]["corr_proj_vs_lora_delta"] = float(
                np.corrcoef(proj, dnorm)[0, 1])
            summary["L%d" % L]["corr_wnorm_vs_lora_delta"] = float(
                np.corrcoef(wnorm, dnorm)[0, 1])
        for j in top[:40]:
            rows.append({
                "layer": L, "neuron": int(j),
                "align": float(proj[j]), "w_norm": float(wnorm[j]),
                "lora_delta": float(dnorm[j]) if dnorm is not None else None,
            })
        print("  L%-2d 对齐度 max %.4f｜top200 占 %.1f%%｜与‖W‖相关 %.2f"
              % (L, proj.max(), 100 * summary["L%d" % L]["top200_share"],
                 summary["L%d" % L]["corr_proj_vs_wnorm"]), flush=True)

with io.open(os.path.join(OUT, "top_neurons.csv"), "w", encoding="utf-8") as f:
    f.write("layer,neuron,align,w_norm,lora_delta\n")
    for r_ in rows:
        f.write("%d,%d,%.6f,%.6f,%s\n"
                % (r_["layer"], r_["neuron"], r_["align"], r_["w_norm"],
                   "" if r_["lora_delta"] is None else "%.6f" % r_["lora_delta"]))
with io.open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
print("\n写出 %s（%d 行）" % (OUT, len(rows)))
print(json.dumps(summary, ensure_ascii=False, indent=1)[:800])
