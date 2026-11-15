# -*- coding: utf-8 -*-
"""拆 gemma-4-e4b-it：真正独特的结构 + 各部分参数占比 + LoRA 覆盖盲区。"""
from __future__ import annotations

import io
import json
import os
import re
import struct
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
BASE = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")

print("=" * 74)
print("① config.json：文本塔的真实形状")
print("=" * 74)
cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8-sig"))
tc = cfg.get("text_config") or cfg
keys = ["architectures", "model_type", "num_hidden_layers", "hidden_size",
        "intermediate_size", "num_attention_heads", "num_key_value_heads",
        "head_dim", "vocab_size", "tie_word_embeddings", "rope_theta",
        "sliding_window", "max_position_embeddings", "hidden_activation",
        "rms_norm_eps", "attn_logit_softcapping", "final_logit_softcapping",
        "query_pre_attn_scalar", "use_bidirectional_attention",
        "per_layer_embed_dim", "num_layers_per_group", "matformer",
        "altup_active", "laurel_active", "audio_token_id", "vision_token_id"]
for k in keys:
    v = tc.get(k, cfg.get(k, "—"))
    if v != "—":
        print("   %-30s %s" % (k, v))
print("\n   text_config 里其余键：%s"
      % [k for k in tc if k not in keys][:18])

print()
print("=" * 74)
print("② 权重按模块归类：谁占参数、LoRA 覆盖到谁")
print("=" * 74)
P = os.path.join(BASE, "model.safetensors")
with open(P, "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    h = json.loads(f.read(n))
ks = [k for k in h if k != "__metadata__"]

def group(name: str) -> str:
    if "vision_tower" in name:
        return "vision_tower"
    if "audio_tower" in name:
        return "audio_tower"
    if "embed_tokens_per_layer" in name:
        return "PLE(embed_tokens_per_layer)"
    if "per_layer_input_gate" in name:
        return "PLE(per_layer_input_gate)"
    if "per_layer_projection" in name:
        return "PLE(per_layer_projection)"
    if "post_per_layer_input_norm" in name:
        return "PLE(post_per_layer_input_norm)"
    if "embed_tokens" in name:
        return "embed_tokens(主词表)"
    for t in ("q_proj", "k_proj", "v_proj", "o_proj"):
        if ".%s." % t in name:
            return "attn." + t
    for t in ("gate_proj", "up_proj", "down_proj"):
        if ".%s." % t in name:
            return "mlp." + t
    if "layernorm" in name or "norm" in name:
        return "norms"
    if "lm_head" in name:
        return "lm_head"
    return "other"

bytes_by = defaultdict(int)
cnt_by = defaultdict(int)
for k in ks:
    o = h[k].get("data_offsets") or [0, 0]
    b = int(o[1]) - int(o[0])
    g = group(k)
    bytes_by[g] += b
    cnt_by[g] += 1

total_b = sum(bytes_by.values())
LORA_TARGETS = {"attn.q_proj", "attn.k_proj", "attn.v_proj", "attn.o_proj",
                "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"}
print("   %-30s %10s %8s %8s  %s" % ("模块", "参数(B)", "占比", "张量", "LoRA"))
acc_lora = 0
for g, b in sorted(bytes_by.items(), key=lambda x: -x[1]):
    params = b / 2
    hit = "✅ 训练" if g in LORA_TARGETS else "❌ 冻结"
    if g in LORA_TARGETS:
        acc_lora += b
    print("   %-30s %10.3f %7.2f%% %8d  %s"
          % (g, params / 1e9, 100 * b / total_b, cnt_by[g], hit))
print("\n   合计 %.3f B 参数｜LoRA 覆盖 %.2f%%"
      % (total_b / 2 / 1e9, 100 * acc_lora / total_b))

print()
print("=" * 74)
print("③ PLE 相关层的具体形状（看它怎么把每层喂进去）")
print("=" * 74)
for k in sorted(ks):
    if any(s in k for s in ("per_layer", "per_layer_projection", "input_gate")):
        o = h[k].get("data_offsets") or [0, 0]
        shape = h[k].get("shape")
        print("   %-58s shape=%s" % (k.replace("model.language_model.", ""), shape))

print()
print("=" * 74)
print("④ 建模源码里有没有 Gemma 独有的稳定性机制")
print("=" * 74)
mp = None
for cand in ("modeling_gemma4.py",):
    p = os.path.join(ROOT, ".venv", "Lib", "site-packages", "transformers",
                     "models", "gemma4", cand)
    if os.path.exists(p):
        mp = p
if mp:
    t = io.open(mp, encoding="utf-8", errors="replace").read()
    for pat, label in ((r"softcap", "logit/attn soft-capping"),
                       (r"qk_norm|q_norm|k_norm", "QK-Norm"),
                       (r"per_layer", "per-layer embedding 注入"),
                       (r"matformer|nested", "MatFormer/嵌套"),
                       (r"sliding_window", "滑窗注意力"),
                       (r"use_cache", "KV cache")):
        hits = len(re.findall(pat, t))
        print("   %-28s 出现 %3d 次" % (label, hits))
else:
    print("   没找到 modeling_gemma4.py")
