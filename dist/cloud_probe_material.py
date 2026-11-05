#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""云端：用素材抽的 20 道题检验 v9t6 实际效果（不做判据，只看原文）。"""
import io, json, os, sys, time
sys.path.insert(0, "/root/yh")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel
from unified_prompt import UNIFIED_SYSTEM

BASE = os.environ.get("YH_MODEL", "/root/autodl-tmp/models/gemma-4-e4b-it")
ADAPTER = os.environ.get("YH_ADAPTER", "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t6")
CASES = json.load(io.open("/root/yh/material_probe20.json", encoding="utf-8"))

tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    BASE, trust_remote_code=True, device_map={"": 0},
    quantization_config=BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True))
model = PeftModel.from_pretrained(model, ADAPTER)
model.eval()

def render(q):
    msgs = [{"role": "system", "content": UNIFIED_SYSTEM},
            {"role": "user", "content": q}]
    for kw in ({}, {"enable_thinking": False}):
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True, **kw)
        except Exception:
            continue
    raise SystemExit("模板渲染失败")

res = []
t0 = time.time()
for i, e in enumerate(CASES, 1):
    text = render(e["q"])
    ids = tok(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=200, do_sample=False,
                             repetition_penalty=1.1,
                             pad_token_id=tok.eos_token_id)
    ans = tok.decode(out[0][ids["input_ids"].shape[1]:],
                     skip_special_tokens=True).strip()
    res.append({"id": e["id"], "cat": e["cat"], "q": e["q"],
                "note": e["note"], "answer": ans})
    print("[%d/%d] %s %s" % (i, len(CASES), e["id"], e["q"][:26]))
    print("      → %s" % ans[:150].replace("\n", " "))

out_p = "/root/autodl-tmp/probe20_material.json"
json.dump({"model": BASE, "adapter": ADAPTER, "elapsed": time.time() - t0,
           "results": res}, io.open(out_p, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\n写出 → %s｜%.1f 分钟" % (out_p, (time.time() - t0) / 60))
