# -*- coding: utf-8 -*-
"""复核修正版：把上一版脚本里的三处错误纠正并重新验。

上一版错在哪：
  ① 我写「第 0 层命中 0 个」——是我拼名字拼错了（多加了 "language_model." 前缀），
     总量才是对的：attention 正则命中 **132 个模块**×2 张量 = 264（v9t8 的实测数）；
     含 MLP 命中 **258 个模块**×2 = 516（v7b 的实测数）。两条完全对得上。
  ② adapter 体积算错：我按 bf16（2 字节）算成 66.5MB，但 PEFT 的 adapter 存的是 **fp32**：
     v9t8 = 9.08M 参数 × 4 = 36.3MB（实测 36,346,288 ✅）；v7b = 34.9M × 4 = 139.6MB（实测 139,602,808 ✅）。
     所以 v9t9 的 adapter 应该是 **≈139.6MB**，不是 66.5MB。
  ③ 上一版同一行里既写 66.5MB 又写「与 v7b 139.6MB 对齐」，自相矛盾。
"""
from __future__ import annotations

import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

import torch  # noqa: E402
from transformers import AutoConfig  # noqa: E402
from transformers.models.gemma4 import modeling_gemma4 as M  # noqa: E402

cfg = AutoConfig.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it",
                                              "config.json"))
with torch.device("meta"):
    model = M.Gemma4ForConditionalGeneration(cfg)

ATT = r".*language_model\.layers\.\d+\.self_attn\.(q|k|v|o)_proj$"
MLP = r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"

print("=== 模块数与张量数（×2 = lora_A/lora_B）===")
for tag, pat, expect in (("attention-only", ATT, 264), ("attention+MLP", MLP, 516)):
    rx = re.compile(pat)
    hits = [n for n, _ in model.named_modules() if rx.fullmatch(n)]
    tensors = len(hits) * 2
    ok = "✅" if tensors == expect else "❌"
    print("  %-14s 模块 %3d → 张量 %3d（实测应为 %d）%s"
          % (tag, len(hits), tensors, expect, ok))

print("\n=== 为什么不是 42 层 × 4/7 ===")
from collections import Counter  # noqa: E402
dist = Counter()
for i in range(len(model.model.language_model.layers)):
    n = sum(1 for name, _ in model.named_modules()
            if re.fullmatch(ATT, name) and ".layers.%d." % i in name)
    dist[n] += 1
print("  每层 attention 模块数分布：%s（层数→模块数）" % dict(dist))
print("  原因：config 里 num_kv_shared_layers=18，那些层没有 k_proj/v_proj")

print("\n=== adapter 体积（fp32，不是 bf16）===")
att_params = 9_076_736
per_layer_mlp = 16 * (2560 + 10240) * 2 + 16 * (10240 + 2560)
mlp_params = per_layer_mlp * 42
total = att_params + mlp_params
print("  attention %.2fM + MLP %.2fM = **%.2fM** 参数" % (att_params / 1e6, mlp_params / 1e6,
                                                       total / 1e6))
print("  × 4 字节（fp32）= **%.1f MB**" % (total * 4 / 1048576))
print("  对照：v9t8 9.08M×4=36.3MB（实测 36,346,288）｜v7b 34.9M×4=139.3MB（实测 139,602,808）")

print("\n=== 训练账 ===")
n_train, bs, ga = 6155, 4, 2
steps = math.ceil(n_train / (bs * ga))
print("  步数 %d｜按 2.97–3.03 s/步 → %.0f–%.0f 分钟" % (steps, steps * 2.97 / 60, steps * 3.03 / 60))
print("  checkpoint：save_steps=200 → 3 次保存 ×139.6MB ≈ 419MB，磁盘充足（云端剩 27G）")
