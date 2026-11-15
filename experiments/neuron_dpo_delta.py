# -*- coding: utf-8 -*-
"""对比两条改动的「集中度」：
  · 拒绝方向的对齐度（已知分散）
  · v9t10→dpo2 这轮 DPO 真正改动的神经元
同样是 top-K 占比，看风格是不是也是分布的。
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
from safetensors import safe_open

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
A1 = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t10", "adapter_model.safetensors")
A2 = os.path.join(YH, "models", "lora", "yuanheng-v9t10-dpo2", "adapter_model.safetensors")
OUT = os.path.join(YH, "dist", "neuron_report", "dpo_delta.json")
LAYERS = [12, 16, 20, 24, 28]


def load_delta(path, L):
    """返回这一层 down_proj 每个神经元的增量强度 ‖B·A[:, j]‖"""
    with safe_open(path, framework="pt", device="cpu") as f:
        ka = "base_model.model.model.language_model.layers.%d.mlp.down_proj.lora_A.weight" % L
        kb = "base_model.model.model.language_model.layers.%d.mlp.down_proj.lora_B.weight" % L
        if ka not in f.keys() or kb not in f.keys():
            return None
        A = f.get_tensor(ka).float().numpy()
        B = f.get_tensor(kb).float().numpy()
    return np.linalg.norm(B @ A, axis=0)


res = {}
for L in LAYERS:
    d1 = load_delta(A1, L)
    d2 = load_delta(A2, L)
    if d1 is None or d2 is None:
        continue
    d = np.abs(d2 - d1)                       # DPO 相对 v9t10 的净改动
    tot = d.sum()
    order = np.argsort(-d)
    def share(k):
        return float(d[order[:k]].sum() / tot)
    res["L%d" % L] = {
        "top10_share": share(10), "top100_share": share(100),
        "top200_share": share(200), "top1000_share": share(1000),
        "max_over_mean": float(d.max() / d.mean()),
        "n_neurons": int(d.size),
    }
    print("L%-2d DPO 改动：top10 %.1f%%｜top100 %.1f%%｜top200 %.1f%%｜top1000 %.1f%%｜max/mean %.1f"
          % (L, 100 * res["L%d" % L]["top10_share"], 100 * res["L%d" % L]["top100_share"],
             100 * res["L%d" % L]["top200_share"], 100 * res["L%d" % L]["top1000_share"],
             res["L%d" % L]["max_over_mean"]), flush=True)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print("\n写出 %s" % OUT)
print("\n对照：拒绝方向 top200 只占 7–8%%，且 10240 个神经元里 top1000 才 %.1f%% 就是均匀分布(9.8%%)"
      % 0.0)
