#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从训练语料里随机抽 10 条提问，让模型现场回答，和语料原答对照。

目的：56 题是回归测试（判据死板），这个是**直观效果**——看它说话的质感。

用法：
    python tools/v9_sample10.py                 # 随机 10 条
    python tools/v9_sample10.py --n 10 --seed 7
    python tools/v9_sample10.py --dim scene     # 只从某维度抽
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
TRAIN = os.path.join(ROOT, "data", "finetune", "sft_persona_v9t_train.jsonl")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--dim", default="")
    a = ap.parse_args()

    rows = [json.loads(x) for x in io.open(TRAIN, encoding="utf-8") if x.strip()]
    # 只抽纯对话（user + assistant 各一条，无 tool_calls），这样对照直观
    pool = []
    for r in rows:
        msgs = r["messages"]
        if any(m.get("tool_calls") for m in msgs):
            continue
        u = next((m["content"] for m in msgs if m["role"] == "user"), "")
        asst = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        if not u.strip() or not asst.strip():
            continue
        dim = str(r.get("source", "?")).split(":")[0]
        if a.dim and dim != a.dim:
            continue
        pool.append({"dim": dim, "src": str(r.get("source", "?")),
                     "user": u.strip(), "gold": asst.strip()})
    print("候选池 %d 条" % len(pool))

    random.seed(a.seed)
    picks = random.sample(pool, min(a.n, len(pool)))
    from collections import Counter
    print("抽中维度分布：%s\n" % dict(Counter(p["dim"] for p in picks)))

    import torch
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
    print("就绪\n")

    for i, p in enumerate(picks, 1):
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": p["user"]}]
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
            out = model.generate(**ids, max_new_tokens=400, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        ans = tok.decode(out[0][ids["input_ids"].shape[1]:],
                         skip_special_tokens=True).strip()

        print("=" * 74)
        print("【%d/%d】来源：%s ｜ %s" % (i, len(picks), p["dim"], p["src"][:34]))
        print("-" * 74)
        print("问（语料里的原提问）：")
        print("  " + p["user"].replace("\n", "\n  "))
        print()
        print("语料原答（训练用的标准答案）：")
        print("  " + p["gold"][:500].replace("\n", "\n  "))
        print()
        print("模型现场答：")
        print("  " + ans[:500].replace("\n", "\n  "))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
