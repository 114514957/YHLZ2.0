# -*- coding: utf-8 -*-
"""遗忘探针：chat 格式下的困惑度（训练前后各跑一次，涨太多就是忘了）。"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--corpus", default="/root/yh/s0_corpus.txt")
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--tag", default="x")
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        a.model, dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
        low_cpu_mem_usage=True)
    model.eval()

    lines = [ln.strip() for ln in io.open(a.corpus, encoding="utf-8", errors="replace")
             if 40 < len(ln.strip()) < 300][:a.n]
    tot = cnt = 0.0
    n_used = 0
    with torch.no_grad():
        for ln in lines:
            msgs = [{"role": "user", "content": "说点什么"},
                    {"role": "assistant", "content": ln}]
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            ids = tok(text, return_tensors="pt", truncation=True,
                      max_length=256).to("cuda")["input_ids"]
            if ids.shape[1] < 8:
                continue
            loss = model(input_ids=ids, labels=ids).loss
            tot += float(loss) * ids.shape[1]
            cnt += ids.shape[1]
            n_used += 1
    ppl = math.exp(tot / max(1, cnt))
    out = {"tag": a.tag, "model": a.model, "ppl": round(ppl, 2), "n": n_used}
    print("[%s] chat-PPL = %.2f（%d 段）" % (a.tag, ppl, n_used))
    os.makedirs("/root/yh/results", exist_ok=True)
    with open("/root/yh/results/ppl_%s.json" % a.tag, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
