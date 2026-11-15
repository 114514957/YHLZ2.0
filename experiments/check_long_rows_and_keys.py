# -*- coding: utf-8 -*-
"""把两个红灯查到底：
  ① 60 条超长样本，截断到 1536 token 后会不会变成"全 -100"被丢？
  ② 配置缺的那 5 个键，哪些是**无默认值**的真风险（其余是 CLI/全量分支专用）。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TRAIN = os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_train.jsonl")
TRAINER = os.path.join(ROOT, "dist", "material_v13", "train_v13.py")
MAX_LEN = 1536

rows = [json.loads(x) for x in io.open(TRAIN, encoding="utf-8", errors="replace") if x.strip()]
long_rows = [r for r in rows
             if sum(len(str(m.get("content") or "")) for m in r["messages"]) > 1400]
print("超长样本 %d 条，逐条按 tokenizer 复现截断后的标签情况" % len(long_rows))

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf",
                                                 "gemma-4-e4b-it"))
# 复现训练器的编码逻辑：从右侧截断，mask_prompt 把 assistant 之前置 -100
all_bad = 0
truncated = 0
for r in long_rows:
    msgs = [m for m in r["messages"] if isinstance(m, dict)]
    ids: list[int] = []
    labels: list[int] = []
    for i, m in enumerate(msgs):
        txt = str(m.get("content") or "")
        seg = tok(txt, add_special_tokens=False)["input_ids"]
        if m.get("role") == "assistant":
            labels += list(seg)
        else:
            labels += [-100] * len(seg)
        ids += list(seg)
    if len(ids) > MAX_LEN:
        truncated += 1
        ids = ids[:MAX_LEN]
        labels = labels[:MAX_LEN]
    if all(x == -100 for x in labels):
        all_bad += 1

print("  其中会被截断：%d 条" % truncated)
print("  截断后变成『全 -100』被丢：%d 条" % all_bad)
print("  → 影响：%.2f%% 的样本（可接受）" % (100 * all_bad / len(rows)))
# 整体估算：全部样本里有多少会因长度被丢
bad_all = 0
for r in rows:
    ids, labels = [], []
    for m in r["messages"]:
        seg = tok(str(m.get("content") or ""), add_special_tokens=False)["input_ids"]
        labels += list(seg) if m.get("role") == "assistant" else [-100] * len(seg)
        ids += list(seg)
    if len(ids) > MAX_LEN:
        labels = labels[:MAX_LEN]
    if all(x == -100 for x in labels):
        bad_all += 1
print("全量预估：会因『全 -100』被丢 %d 条（%.2f%%）" % (bad_all, 100 * bad_all / len(rows)))

# ── ② 配置缺键：区分"无默认值"与"有默认值" ──────────────────────────
src = io.open(TRAINER, encoding="utf-8").read()
direct = set(re.findall(r'cfg\[["\']([a-z_0-9]+)["\']\]', src))
with_def = set(re.findall(r'cfg\.get\(["\']([a-z_0-9]+)["\'],', src))
no_default = set(re.findall(r'cfg\.get\(["\']([a-z_0-9]+)["\']\)', src))
cfg = json.load(io.open(os.path.join(ROOT, "dist", "material_v14", "config",
                                     "finetune.gemma4.v14.json"), encoding="utf-8"))
critical = sorted((direct | no_default) - set(cfg))
print("\n**无默认值**的键缺哪些（真风险）：%s" % (critical or "无"))
print("直接访问 cfg[...] 的键：%s" % sorted(direct))
print("有默认值的键（缺了也没事）：%s"
      % sorted((with_def - set(cfg)) - {"eval_batch_size", "freeze_external"}))
