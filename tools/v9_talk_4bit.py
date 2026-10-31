#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""4bit 加载测模型说话（本机 4060 8.6 GB 装不下 bf16 的 7.49 GiB）。

用量化换空间：4bit 后约 2.2 GB，8 GB 卡轻松跑。
代价是精度略降，但看口吻够用。

用法：
    python tools/v9_talk_4bit.py
    python tools/v9_talk_4bit.py --ask "在吗" "今天有点累" "你叫什么"
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", nargs="*", default=None)
    ap.add_argument("--max-new", type=int, default=200)
    a = ap.parse_args()

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    print("加载 4bit 模型（约 2.2 GB 显存）…")
    t0 = time.time()
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()
    print("✅ 加载完成 %.1f 秒｜显存 %.2f GB\n"
          % (time.time() - t0, torch.cuda.memory_allocated() / 1e9))

    qs = a.ask or [
        "在吗",
        "你叫什么",
        "今天有点累",
        "你说人为什么爱熬夜",
        "我回来了",
        "帮我把桌面收拾一下",
    ]
    for q in qs:
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
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=a.max_new,
                                 do_sample=False, repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        dt = time.time() - t1
        ans = tok.decode(out[0][ids["input_ids"].shape[1]:],
                         skip_special_tokens=True).strip()
        ntok = out.shape[1] - ids["input_ids"].shape[1]
        print("问：%s" % q)
        print("答：%s" % ans)
        print("    （%d tok / %.1f 秒 = %.1f tok/s）\n" % (ntok, dt, ntok / dt if dt else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
