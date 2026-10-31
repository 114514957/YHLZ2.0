#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""POC：本地 4bit 模型上做 MLP 神经元 steering（transformers hook）。

为什么先做这个：neuron-explorer 的档案说需要「CUDA 13 + 4090 pod + vLLM steering fork」，
但 steering 的数学只有一句：
    mlp_out += strength * W_down[:, n]
transformers 注册 forward hook 就能实现，不需要 vLLM fork。

本脚本验证四件事：
  ① 4bit 模型能不能取到 down_proj 的第 n 列（量化权重能不能 dequantize 出单列）
  ② 能不能注册 hook 并在 mlp 输出上加向量
  ③ 推了之后输出**真的会变**（不变就是没生效）
  ④ 正负方向有没有区分度（不是随便什么方向都能改）

用法：
    python tools/v9_steer_poc.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")


def main() -> int:
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    print("=" * 70)
    print("① 加载 4bit 模型")
    print("=" * 70)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()
    n_layers = len(model.model.layers)
    hidden = model.config.hidden_size
    inter = model.config.intermediate_size
    print("  ✅ 层数 %d｜hidden %d｜intermediate %d" % (n_layers, hidden, inter))

    print("\n" + "=" * 70)
    print("② 能不能取到 down_proj 的第 n 列")
    print("=" * 70)
    LAYER = 11
    mlp = model.model.layers[LAYER].mlp
    w = mlp.down_proj.weight
    print("  down_proj.weight: %s dtype=%s shape=%s"
          % (type(w).__name__, w.dtype, tuple(w.shape)))
    # bnb 的 Params4bit 是打包存储（dequantize 不给真实形状），
    # 直接从 safetensors 按名读原始 bf16 权重，最干净。
    from safetensors import safe_open
    st_path = os.path.join(MODEL, "model.safetensors")
    tname = "model.layers.%d.mlp.down_proj.weight" % LAYER
    with safe_open(st_path, framework="pt") as f:
        wd = f.get_tensor(tname)
    print("  safetensors 直读：%s dtype=%s shape=%s"
          % (tname, wd.dtype, tuple(wd.shape)))
    col = wd[:, 1234].to(torch.bfloat16)
    print("  ✅ 第 1234 列：shape=%s norm=%.4f"
          % (tuple(col.shape), col.float().norm().item()))

    print("\n" + "=" * 70)
    print("③ 注册 hook，推方向，看输出变不变")
    print("=" * 70)
    state = {"d": None}

    def make_hook():
        def hook(module, args, output):
            if state["d"] is None:
                return output
            return output + state["d"]
        return hook

    h = mlp.register_forward_hook(make_hook())
    print("  ✅ hook 已注册在 layers[%d].mlp" % LAYER)

    def gen(q: str, max_new: int = 60) -> str:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": q}]
        try:
            kw = {"enable_thinking": False}
            try:
                text = tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True, **kw)
            except TypeError:
                text = tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True)
        except Exception:  # noqa: BLE001
            text = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)
        ids = tok(text, return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=max_new, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()

    Q = "在吗"
    state["d"] = None
    base = gen(Q)
    print("\n  [baseline] %s" % base[:120].replace("\n", " "))

    results = []
    for frac in (0.5, 1.0, 2.0, -1.0, -2.0):
        state["d"] = (col * frac).to("cuda:0")
        t = gen(Q)
        results.append((frac, t))
        print("  [d=%+.1f×col] %s" % (frac, t[:120].replace("\n", " ")))

    changed = sum(1 for _, t in results if t != base)
    distinct = len({t for _, t in results})
    print("\n  输出与 baseline 不同的剂量：%d/%d" % (changed, len(results)))
    print("  不同输出的种数：%d（含 baseline 共 %d）" % (distinct, distinct + 1))

    h.remove()
    print("\n" + "=" * 70)
    if changed >= 3 and distinct >= 3:
        print("✅ POC 通过：hook 生效、输出可控、不同剂量有区分度")
        print("   → 本地 4bit steering 可行，不需要 vLLM fork 和 4090 pod")
        return 0
    print("⚠ 效应偏弱：改变 %d/%d、区分度 %d。可能需要换层/换神经元，或加大剂量。"
          % (changed, len(results), distinct))
    return 2


if __name__ == "__main__":
    sys.exit(main())
