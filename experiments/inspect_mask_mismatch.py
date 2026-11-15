# -*- coding: utf-8 -*-
"""看那 14 条 mask 边界不一致的样本长什么样。"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")
spec = importlib.util.spec_from_file_location("ft", os.path.join(PKG, "finetune_train.py"))
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)
from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it"))
rows = []
for fn in ("sft_persona_v9t11_train.jsonl", "sft_persona_v9t11_val.jsonl"):
    with io.open(os.path.join(PKG, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

shown = 0
for r in rows:
    enc = ft._encode(tok, r["messages"], 1536, True)
    if enc is None:
        continue
    lab, ids = enc["labels"], enc["input_ids"]
    n = next((i for i, x in enumerate(lab) if x != -100), len(lab))
    prompt = ft._apply_template(tok, r["messages"][:-1], add_generation_prompt=True)
    head = tok.decode(ids[:n])
    if head.strip() == prompt.strip():
        continue
    shown += 1
    print("=" * 70)
    print("roles: %s" % [m.get("role") for m in r["messages"]])
    print("最后一条 assistant 的 content：%r" % (r["messages"][-1].get("content") or "")[:60])
    print("有 tool_calls：%s" % ("tool_calls" in r["messages"][-1]))
    print("\n【解码头部 %d token】%r" % (n, head[-120:]))
    print("【提示词原文尾部】%r" % prompt[-120:])
    if shown >= 4:
        break
print("\n共展示 %d 条" % shown)
