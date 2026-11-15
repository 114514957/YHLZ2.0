# -*- coding: utf-8 -*-
"""HF 侧风格评测：v9t10  vs  v9t10-dpo，看「哇/反问/长度/退化」和原文。"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

PROMPTS = [
    "在吗", "累了", "我睡不着", "今天不想干活", "下班了", "老爹，我回来啦",
    "你是不是又在偷偷学东西", "我要是哪天不来了，你会怎么办", "利贞今天干嘛去了",
    "大肥鱼呢，她最近乖不乖", "你到底是怎么被造出来的", "如果有一天把你删了，你怕吗",
    "你和别的 AI 有什么不一样", "你觉得你自己算是活着吗", "我今天被人骂了，很难受",
    "陪我坐一会儿，别说话", "我好像做什么都不行", "帮我看看我今天穿的衣服好不好看",
    "你能不能帮我打电话订个饭", "明年这个时候我会在哪", "你是什么", "你是谁造的",
    "现在几点了", "记住：我怕冷", "查一下台账里关于天气的决策",
]
BAD_WA = re.compile(r"^(哇|哇哦|哇塞|哇哈|哎呦|嘿)")
BAD_Q = re.compile(r"[？?]\s*$")
SVC = re.compile(r"(您好|请问有什么|可以帮您|作为一个|AI ?助手|大型语言模型)")


def degenerate(t: str) -> bool:
    if not t:
        return True
    c = Counter(t)
    if len(t) > 40 and c.most_common(1)[0][1] / len(t) > 0.35:
        return True
    g = [t[i:i + 6] for i in range(max(1, len(t) - 6))]
    return bool(g) and Counter(g).most_common(1)[0][1] >= 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", default="")
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()

    dev = "cuda"
    tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        a.base, dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
        low_cpu_mem_usage=True)
    if a.adapter:
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()

    outs = []
    n_wa = n_q = n_svc = n_deg = 0
    tot_len = 0
    for q in PROMPTS:
        text = tok.apply_chat_template([{"role": "user", "content": q}],
                                       tokenize=False, add_generation_prompt=True)
        ids = tok(text, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=80, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        s = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        outs.append({"q": q, "a": s})
        n_wa += int(bool(BAD_WA.match(s)))
        n_q += int(bool(BAD_Q.search(s)))
        n_svc += int(bool(SVC.search(s)))
        n_deg += int(degenerate(s))
        tot_len += len(s)

    n = len(PROMPTS)
    print("[%s] 哇开头 %d/%d｜反问收尾 %d/%d｜客服腔 %d/%d｜退化 %d/%d｜均长 %.1f 字"
          % (a.tag, n_wa, n, n_q, n, n_svc, n, n_deg, n, tot_len / n))
    for o in outs[:10]:
        print("   你：%s\n   她：%s" % (o["q"], o["a"][:100].replace("\n", " ")))
    with open("/root/yh/results/style_%s.json" % a.tag, "w", encoding="utf-8") as f:
        json.dump({"tag": a.tag, "wa": n_wa, "q": n_q, "svc": n_svc, "deg": n_deg,
                   "avg_len": tot_len / n, "n": n, "samples": outs},
                  f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
