# -*- coding: utf-8 -*-
"""把 v12-A 的公式代入真数字：步数、warmup、各点 lr、每步 token、总 token。"""
from __future__ import annotations

import io
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10",
                   "sft_persona_v9t10_train.jsonl")

rows = [json.loads(x) for x in io.open(SRC, encoding="utf-8", errors="replace") if x.strip()]
n = len(rows)
B, GA = 4, 2
eff = B * GA
seq = 1536
lr, warm, ep = 2e-4, 0.03, 1.0

steps = math.ceil(n / eff)
warm_steps = max(1, int(warm * steps * ep))
print("样本 %d｜有效 batch %d｜steps/epoch %d｜总步数 %d｜warmup 步 %d"
      % (n, eff, steps, int(steps * ep), warm_steps))

# 真实 token（抽 300 条估平均）
try:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it"))
    import random
    random.seed(0)
    samp = random.sample(rows, min(300, n))
    tot = 0
    for r in samp:
        txt = ""
        for m in r.get("messages") or []:
            txt += ("user: " if m.get("role") == "user" else "assistant: ") + str(m.get("content") or "") + "\n"
        tot += len(tok.encode(txt, add_special_tokens=False))
    mean_tok = tot / len(samp)
    print("平均每条 %.0f token（抽样 %d 条）" % (mean_tok, len(samp)))
    print("每步 token ≈ %.0f（8 条，含 padding 后按实际长度）" % (mean_tok * eff))
    print("全量 token ≈ %.1fM" % (mean_tok * n / 1e6))
    print("按 1536 截断后上限：每步最多 %d token" % (eff * seq))
except Exception as ex:  # noqa: BLE001
    print("tokenizer 不可用：%s" % ex)

# lr 曲线（cosine with warmup，min_lr_ratio=0）
def lr_at(step: int) -> float:
    if step < warm_steps:
        return lr * step / max(1, warm_steps)
    prog = (step - warm_steps) / max(1, (steps - warm_steps))
    return lr * 0.5 * (1 + math.cos(math.pi * min(1.0, prog)))

print("\n学习率采样点（cosine + warmup）")
for s in (0, 1, 10, warm_steps, 100, steps // 2, int(steps * 0.9), steps):
    print("   step %4d → lr %.3e" % (s, lr_at(s)))

print("\n梯度裁剪：g ← g · min(1, 1.0/‖g‖)，只有 ‖g‖>1 时才缩放")
print("实测历史 grad_norm p95 = 3.36（v9t10）→ 该点会缩放到 1.0，约占 5% 的步")
