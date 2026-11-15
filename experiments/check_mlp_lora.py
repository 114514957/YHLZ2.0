# -*- coding: utf-8 -*-
"""决定性验证：文本塔的 MLP 能不能挂 LoRA。

用 meta 设备建模型（不加载任何权重，几乎不占内存），直接看：
  1. layers[0].mlp.gate_proj 到底是什么类
  2. PEFT 用含 gate/up/down 的 target_modules 能不能挂上、挂了多少个
对照：只用 attention 的正则能挂多少
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

import torch  # noqa: E402
import transformers  # noqa: E402
from transformers import AutoConfig  # noqa: E402

print("transformers %s｜torch %s" % (transformers.__version__, torch.__version__))

CFG = os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it", "config.json")
cfg = AutoConfig.from_pretrained(CFG)
print("模型类：%s" % cfg.architectures)

from transformers.models.gemma4 import modeling_gemma4 as M  # noqa: E402

with torch.device("meta"):
    model = M.Gemma4ForConditionalGeneration(cfg)

text = model.model.language_model
print("\n=== 模块类 ===")
for name, mod in list(text.layers[0].named_modules())[:12]:
    if name:
        print("  %-14s %s" % (name, type(mod).__name__))

print("\n判定：")
for path in ("mlp.gate_proj", "mlp.up_proj", "mlp.down_proj", "self_attn.q_proj"):
    mod = text.get_submodule("layers.0." + path)
    print("  layers.0.%-18s -> %s%s"
          % (path, type(mod).__name__,
             "  ✅ 普通 Linear，PEFT 能认" if isinstance(mod, torch.nn.Linear) else "  ❌ 非标准 Linear"))

# 用 PEFT 真挂一次（meta 上也能建 LoRA 模块）
from peft import LoraConfig, get_peft_model  # noqa: E402

print("\n=== PEFT 挂载试验 ===")
for tag, tm in (
    ("attention-only（现在四版用的）",
     r".*language_model\.layers\.\d+\.self_attn\.(q|k|v|o)_proj$"),
    ("attention+MLP（v7b 用的）",
     r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"),
):
    try:
        pm = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                              target_modules=tm, task_type="CAUSAL_LM"))
        n = sum(1 for k, _ in pm.named_parameters() if "lora_" in k)
        mods = set()
        for k, _ in pm.named_parameters():
            if "lora_A" in k:
                mods.add(k.split(".lora_A")[0].split(".")[-2])
        print("  %-28s 可训参数张量 %4d｜模块种类 %s" % (tag, n, sorted(mods)))
    except Exception as ex:  # noqa: BLE001
        print("  %-28s ❌ %s: %s" % (tag, type(ex).__name__, str(ex)[:120]))
    # 复位（重新建 meta 模型，避免叠加）
    with torch.device("meta"):
        model = M.Gemma4ForConditionalGeneration(cfg)
    text = model.model.language_model
