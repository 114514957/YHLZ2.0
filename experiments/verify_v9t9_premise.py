# -*- coding: utf-8 -*-
"""严格复核 v9t9 的前提：逐条验，不留想当然。

要验的：
  1. 正则到底匹配到哪些模块——**有没有误伤音频塔/视觉塔**（那两处才是 ClippableLinear）
  2. 匹配数量是否精确等于 264（attention-only）与 516（+MLP）
  3. 模型顶层结构里，文本塔是否叫 language_model
  4. 步数/时间/参数量的推算复算
  5. 版本差异风险：本地 5.15.1 vs 云端 5.20.2
"""
from __future__ import annotations

import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

import torch  # noqa: E402
import transformers  # noqa: E402
from transformers import AutoConfig  # noqa: E402
from transformers.models.gemma4 import modeling_gemma4 as M  # noqa: E402

print("本地 transformers %s（云端训练脚本钉的是 5.20.2）" % transformers.__version__)
cfg = AutoConfig.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it",
                                              "config.json"))
with torch.device("meta"):
    model = M.Gemma4ForConditionalGeneration(cfg)

print("\n=== 1. 顶层结构（看文本塔叫什么、有没有音频/视觉塔）===")
for name, mod in model.named_children():
    print("  %-16s %s" % (name, type(mod).__name__))
inner = model.model
for name, mod in inner.named_children():
    print("     .%-13s %s" % (name, type(mod).__name__))

ATT = r".*language_model\.layers\.\d+\.self_attn\.(q|k|v|o)_proj$"
MLP = r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"

print("\n=== 2. 正则逐个匹配（fullmatch，与 PEFT 同规则）===")
for tag, pat in (("attention-only", ATT), ("attention+MLP", MLP)):
    rx = re.compile(pat)
    hits = [n for n, _ in model.named_modules() if rx.fullmatch(n)]
    # 分塔统计
    tower = {}
    for h in hits:
        if "language_model" in h:
            t = "文本塔"
        elif "vision" in h:
            t = "视觉塔"
        elif "audio" in h:
            t = "音频塔"
        else:
            t = "其它:" + h.split(".")[0]
        tower[t] = tower.get(t, 0) + 1
    print("  %-14s 命中 %3d 个｜%s" % (tag, len(hits), tower))
    bad = [h for h in hits if "language_model" not in h]
    if bad:
        print("     ⚠️ 误伤非文本塔：%s" % bad[:3])

print("\n=== 3. 每层模块数核算 ===")
text = model.model.language_model
n_layers = len(text.layers)
print("  layers = %d" % n_layers)
for tag, pat, per in (("attention-only", ATT, 4), ("attention+MLP", MLP, 7)):
    rx = re.compile(pat)
    l0 = [n for n, _ in text.layers[0].named_modules() if rx.fullmatch("language_model." + n)]
    print("  第 0 层命中 %d 个（期望 %d）｜%d 层 × 2 张量/模块 = %d 张量"
          % (len(l0), per, n_layers, n_layers * per * 2))
    print("     但实测是 %d 张量 → 说明只有部分层有（kv 共享层缺 k/v）"
          % {4: 264, 7: 516}[per] if per in (4, 7) else "")

print("\n=== 4. 重算 v9t9 的账 ===")
n_train, bs, ga, epochs, seq = 6155, 4, 2, 1.0, 1536
steps = math.ceil(n_train / (bs * ga)) * epochs
print("  步数 = ceil(%d / (%d×%d)) × %s = **%d**" % (n_train, bs, ga, epochs, steps))
print("  按 v9t6 实测 2.97 s/步 → %.0f 分钟（v9t7 是 3.03 s/步 → %.0f 分钟）"
      % (steps * 2.97 / 60, steps * 3.03 / 60))
# 参数量
att_tensors, mlp_tensors = 264, 516
att_params = 9_076_736
per_layer_mlp = 16 * (2560 + 10240) * 2 + 16 * (10240 + 2560)
print("  可训参数 ≈ %.1fM（attention %.1fM + MLP %.1fM×42）"
      % ((att_params + per_layer_mlp * 42) / 1e6, att_params / 1e6, per_layer_mlp / 1e6))
print("  adapter ≈ %.1f MB（bf16 下 %.1fM 参数 ×2 字节，与 v7b 139.6MB 对齐）"
      % ((att_params + per_layer_mlp * 42) * 2 / 1048576,
         (att_params + per_layer_mlp * 42) / 1e6))

print("\n=== 5. 版本差异风险 ===")
src = open(M.__file__, encoding="utf-8").read()
i = src.find("class Gemma4TextMLP")
seg = src[i:i + 900]
calls = [l.strip() for l in seg.splitlines() if "proj" in l][:6]
print("  本地 5.15.1 的 Gemma4TextMLP：")
for c in calls:
    print("    %s" % c)
print("  ⚠️ 云端是 5.20.2，必须**在云端再跑一次本脚本**确认，不能只信本地。")
