#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""特异性检验：随机神经元推 +1.0，输出会不会都变？

这决定 steering 方案是否成立：
  · 若**多数随机神经元**都能改变输出 → 那只是"加噪声"，不特异，找神经元没意义
  · 若**少数**有效 → 说明真有功能特异的神经元，值得扫

方法：随机抽 N 个神经元（固定种子），每个推 +1.0，用「在吗」生成，
与 baseline 比较（完全相同=无效，不同=有效），并统计"变短"的比例。

用法：
    python tools/v9_steer_specificity.py --layer 11 --n 24
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", type=int, default=11)
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--dose", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--q", default="在吗")
    a = ap.parse_args()

    import torch
    from safetensors import safe_open
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    print("加载 4bit 模型 …")
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()

    mlp = model.model.layers[a.layer].mlp
    state = {"d": None}

    def hook(module, args, output):
        if state["d"] is None:
            return output
        return output + state["d"]

    h = mlp.register_forward_hook(hook)

    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": a.q}]
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

    def gen():
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=50, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()

    state["d"] = None
    base = gen()
    print("\n[baseline] %s\n" % base.replace("\n", " "))

    with safe_open(os.path.join(MODEL, "model.safetensors"), framework="pt") as f:
        wd = f.get_tensor("model.layers.%d.mlp.down_proj.weight" % a.layer)
    wd = wd.to(torch.bfloat16).to("cuda:0")
    inter = wd.shape[1]

    random.seed(a.seed)
    picks = random.sample(range(inter), a.n)
    same, diff, shorter = 0, 0, 0
    outs = []
    for i, n in enumerate(picks, 1):
        state["d"] = (wd[:, n] * a.dose).to(torch.bfloat16)
        t = gen()
        state["d"] = None
        tag = "同" if t == base else "变"
        if t == base:
            same += 1
        else:
            diff += 1
            if len(t) < len(base) * 0.7:
                shorter += 1
        outs.append({"neuron": n, "out": t, "changed": t != base})
        print("  %2d/%d N%-5d [%s] %s" % (i, a.n, n, tag, t[:95].replace("\n", " ")))

    h.remove()
    print("\n" + "=" * 68)
    print("随机 %d 个神经元，剂量 %+.1f" % (a.n, a.dose))
    print("  输出不变：%d（%.0f%%）" % (same, 100.0 * same / a.n))
    print("  输出改变：%d（%.0f%%）" % (diff, 100.0 * diff / a.n))
    print("  其中明显变短（<70%%）：%d" % shorter)
    print("=" * 68)
    if diff >= a.n * 0.8:
        print("⚠ 绝大多数随机神经元都能改变输出 → 这是**加噪声**，不特异。")
        print("   找特定神经元的价值不高；steering 更适合做「整体风格偏移」而非「修某个行为」。")
    elif diff >= a.n * 0.3:
        print("◐ 约三到八成有效 → 有一定选择性，但需要大样本才能筛出真正的特异神经元。")
    else:
        print("✅ 多数随机神经元无效 → **存在功能特异的神经元**，值得系统扫描。")

    os.makedirs(os.path.join(ROOT, "cache", "neuron"), exist_ok=True)
    p = os.path.join(ROOT, "cache", "neuron", "specificity_L%d.json" % a.layer)
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump({"layer": a.layer, "dose": a.dose, "q": a.q,
                   "baseline": base, "same": same, "diff": diff,
                   "shorter": shorter, "samples": outs}, f, ensure_ascii=False)
    print("明细：%s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
