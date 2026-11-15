# -*- coding: utf-8 -*-
"""准备 v9t9：**数据用 v9t6（历史最好的单版）**，唯一变量 = target_modules 加上 MLP。

依据（今晚实测）：
  · 文本塔 mlp.gate_proj/up_proj/down_proj 是普通 nn.Linear，PEFT 能挂
  · attention-only 正则 → 264 张量（我们四版就是这个数）
  · attention+MLP 正则 → 516 张量（v7b 就是这个数）
所以「四版只训 attention」是配置遗漏，不是 PEFT 限制（推翻 1049 的归因）。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t6")
DST = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t9")

MLP_RE = (r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|"
          r"gate_proj|up_proj|down_proj)")

os.makedirs(DST, exist_ok=True)
os.makedirs(os.path.join(DST, "config"), exist_ok=True)

for fn in ("finetune_train.py",):
    shutil.copy2(os.path.join(SRC, fn), os.path.join(DST, fn))
for fn in ("sft_persona_v9t6t_train.jsonl", "sft_persona_v9t6t_val.jsonl"):
    dst = os.path.join(DST, fn.replace("v9t6t", "v9t9"))
    shutil.copy2(os.path.join(SRC, fn), dst)
    print("  ✓ %-32s %d 条 %d 字节" % (os.path.basename(dst),
                                     sum(1 for x in io.open(dst, encoding="utf-8") if x.strip()),
                                     os.path.getsize(dst)))

cfg = json.load(io.open(os.path.join(SRC, "config", "finetune.gemma4.v9t6lora.json"),
                        encoding="utf-8"))
cfg["target_modules"] = MLP_RE
cfg["train_file"] = "/root/yh/retrain_pkg_gemma_v9t9/sft_persona_v9t9_train.jsonl"
cfg["val_file"] = "/root/yh/retrain_pkg_gemma_v9t9/sft_persona_v9t9_val.jsonl"
cfg["output_dir"] = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t9"
cfg["_说明"] = ("gemma v9t9：**唯一变量=target_modules 加上 MLP**（q/k/v/o + gate/up/down）。"
                "数据沿用 v9t6（历史最好的单版，5659+82 条），其余超参与 v9t6 一致。"
                "依据：今晚 meta 设备实测，文本塔 MLP 是普通 nn.Linear，PEFT 可挂；"
                "attention-only 264 张量 vs attention+MLP 516 张量。")
p = os.path.join(DST, "config", "finetune.gemma4.v9t9lora.json")
with io.open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("  ✓ 配置 %s" % os.path.basename(p))
print("     target_modules = %s" % MLP_RE)
print("     r=%s α=%s batch=%s/%s epochs=%s seq=%s"
      % (cfg["lora_r"], cfg["lora_alpha"], cfg["batch_size"], cfg["grad_accum"],
         cfg["epochs"], cfg["max_seq_len"]))

# 预估可训参数：attention 9,076,736（v9t7 实测）→ MLP 部分按维度估
# 每层：gate(2560×10240) + up(2560×10240) + down(10240×2560)，r=16 → 16×(2560+10240)*2 + 16×(10240+2560)
per_layer_mlp = 16 * (2560 + 10240) * 2 + 16 * (10240 + 2560)
total = 9_076_736 + per_layer_mlp * 42
print("\n预估可训参数 ≈ %.1f M（attention 9.1M + MLP %.1fM×42 层）"
      % (total / 1e6, per_layer_mlp / 1e6))
print("预估 adapter ≈ %.0f MB（v7b 实测 516 张量 = 133.1 MB）" % (516 / 516 * 133.1))

man = {"version": "v9t9", "base_pkg": "retrain_pkg_gemma_v9t6",
       "only_change": "target_modules 加 gate_proj/up_proj/down_proj",
       "evidence": "experiments/check_mlp_lora.py：文本塔 MLP=nn.Linear；264 vs 516 张量",
       "expected_adapter_mb": 133.1}
with io.open(os.path.join(DST, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(man, f, ensure_ascii=False, indent=1)
print("\n包 → %s" % DST)
