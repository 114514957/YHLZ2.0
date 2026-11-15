# -*- coding: utf-8 -*-
"""审计训练公式：mask 边界对不对、有没有全 -100 的样本、EOS 有没有、weight 有没有被用。

这四条直接决定 loss 和梯度算得对不对，必须用真实数据量，不能靠读代码猜。
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
sys.path.insert(0, PKG)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("ft", os.path.join(PKG, "finetune_train.py"))
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it"))

rows = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    with io.open(os.path.join(PKG, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]
print("样本 %d 条" % len(rows))

# ── 1. weight 字段在不在？训练会不会用到？──
w = Counter(str(r.get("weight")) for r in rows)
print("\n[1] weight 字段分布（前5）：%s" % w.most_common(5))
slim_keys = {"messages_json", "source"}
print("    训练侧 _slim() 只保留 %s → **weight 不进入训练张量**" % slim_keys)

# ── 2. EOS / 结束符 ──
rec = rows[0]
full = ft._apply_template(tok, rec["messages"], add_generation_prompt=False)
ids = tok(full, add_special_tokens=True, truncation=True, max_length=1536)["input_ids"]
tail = tok.decode(ids[-6:])
print("\n[2] 一条样本的结尾 token：%r" % tail)
print("    eos_token=%r｜末 token 是 eos：%s" % (tok.eos_token, ids[-1] == tok.eos_token_id))

# ── 3. mask 边界是否对齐 + 有没有全 -100 ──
random.seed(7)
sample = random.sample(rows, min(400, len(rows)))
bad_prefix = 0
allmask = 0
leak = 0
for r in sample:
    e = ft._encode(tok, r["messages"], 1536, True)
    lab = e["labels"]
    if all(x == -100 for x in lab):
        allmask += 1
        continue
    full = ft._apply_template(tok, r["messages"], add_generation_prompt=False)
    prompt = ft._apply_template(tok, r["messages"][:-1], add_generation_prompt=True)
    ids = tok(full, add_special_tokens=True, truncation=True, max_length=1536)["input_ids"]
    p_ids = tok(prompt, add_special_tokens=True, truncation=True, max_length=1536)["input_ids"]
    n = min(len(p_ids), len(ids))
    if ids[:n] != p_ids[:n]:
        bad_prefix += 1
    # 泄漏检查：被标记为 loss 的第一个 token，是否其实是 prompt 的尾巴
    if n < len(ids) and ids[n:n + 1] == p_ids[n - 1:n]:
        leak += 1

print("\n[3] mask 边界（抽 %d 条）" % len(sample))
print("    前缀不一致（ids[:n] != p_ids[:n]）：**%d 条（%.1f%%）**"
      % (bad_prefix, 100 * bad_prefix / len(sample)))
print("    整条全是 -100（无有效 loss token）：**%d 条（%.1f%%）**"
      % (allmask, 100 * allmask / len(sample)))

# ── 4. 长度分布：截断会不会砍掉回答 ──
lens = [len(tok(ft._apply_template(tok, r["messages"], add_generation_prompt=False),
                add_special_tokens=True)["input_ids"]) for r in sample]
lens.sort()
over = sum(1 for x in lens if x > 1536)
print("\n[4] 序列长度：中位 %d｜p90 %d｜最大 %d｜超 1536 的 %d 条（%.1f%%）"
      % (lens[len(lens) // 2], lens[int(0.9 * len(lens))], lens[-1],
         over, 100 * over / len(lens)))
print("    truncation=True 默认从**右侧**截 → 超长样本的 assistant 结尾会被砍掉")
