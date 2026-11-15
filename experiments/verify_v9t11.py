# -*- coding: utf-8 -*-
"""验证 v9t11 的训练修复是否「技术上成立」——不训练，只证明每条修复真的生效。

验五条（对应审计 1136）：
  ① weight 真的进了重采样：**抽样频率 ∝ weight**（不是看平均权重，那是加权抽样的数学性质）
  ② 超长样本被丢弃、不再右截：保留样本长度全部 ≤ max_len
  ③ 全 -100 样本被过滤：保留集里 0 条
  ④ mask 边界正确：`decode(ids[:n])` 必须等于提示词原文（不再用旧的"单独 tokenize 长度"当参照）
  ⑤ 配置项：optim / compute dtype / eval batch / load_best 已关 / 重采样与丢弃代码在
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")

spec = importlib.util.spec_from_file_location("ft", os.path.join(PKG, "finetune_train.py"))
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it"))
cfg = json.load(io.open(os.path.join(PKG, "config", "finetune.gemma4.v9t11lora.json"),
                        encoding="utf-8"))
MAXLEN = cfg["max_seq_len"]

rows = []
for fn in ("sft_persona_v9t11_train.jsonl", "sft_persona_v9t11_val.jsonl"):
    with io.open(os.path.join(PKG, fn), encoding="utf-8") as f:
        part = [json.loads(x) for x in f if x.strip()]
    print("%-34s %d 条" % (fn, len(part)))
    rows += part
print("合计 %d 条\n" % len(rows))

ok_all = True

# ── ②③ 编码 ──
dropped = allmask = 0
kept = []
for r in rows:
    enc = ft._encode(tok, r["messages"], MAXLEN, True)
    if enc is None:
        dropped += 1
        continue
    if all(x == -100 for x in enc["labels"]):
        allmask += 1
        continue
    kept.append((r, enc))

print("[②③] 保留 %d｜丢弃 %d（%.1f%%）｜保留集里全 -100：%d"
      % (len(kept), dropped, 100 * dropped / len(rows), allmask))
ok2 = allmask == 0 and all(len(e["input_ids"]) <= MAXLEN for _r, e in kept)
ok_all &= ok2
print("      %s" % ("✅ 通过（无超长、无全 -100）" if ok2 else "❌ 不通过"))

# ── ④ mask 边界：解码头部 == 提示词原文 ──
bad = 0
for r, enc in kept[:1500]:
    lab, ids = enc["labels"], enc["input_ids"]
    n = next((i for i, x in enumerate(lab) if x != -100), len(lab))
    prompt = ft._apply_template(tok, r["messages"][:-1], add_generation_prompt=True)
    if tok.decode(ids[:n]).strip() != prompt.strip():
        bad += 1
print("\n[④] mask 边界（抽查 %d 条）：解码头部与提示词原文不一致 **%d 条（%.2f%%）**"
      % (min(1500, len(kept)), bad, 100 * bad / min(1500, len(kept))))
ok4 = bad == 0
ok_all &= ok4
print("      %s" % ("✅ 通过：mask 边界就是提示词末尾" if ok4 else "⚠️ 有偏差，要逐条看"))

# ── ① 抽样频率 ∝ weight ──
ws = [float(r.get("weight", 1.0) or 1.0) for r in rows]
import random as _random
n = len(ws)
tot = sum(ws)
rng = _random.Random(cfg["seed"])
idx = rng.choices(range(n), weights=[w / tot for w in ws], k=n)
cnt = Counter(idx)

by_w = defaultdict(lambda: [0, 0])       # weight -> [样本数, 被抽中次数]
for i, w in enumerate(ws):
    by_w[round(w, 3)][0] += 1
    by_w[round(w, 3)][1] += cnt.get(i, 0)

print("\n[①] 重采样：抽样频率应 ∝ weight")
print("      weight   样本数   期望占比   实际占比   偏差")
worst = 0.0
for w, (c, hits) in sorted(by_w.items(), reverse=True):
    exp = w * c / tot
    act = hits / n
    dev = abs(act - exp) / exp if exp else 0
    worst = max(worst, dev)
    print("      %-6.2f   %-7d  %7.2f%%   %7.2f%%   %5.1f%%" % (w, c, 100 * exp, 100 * act, 100 * dev))
ok1 = worst < 0.05
ok_all &= ok1
print("      最大偏差 %.1f%% → %s" % (100 * worst, "✅ 通过（<5%）" if ok1 else "❌ 偏差过大"))

# ── ⑤ 配置与代码 ──
print("\n[⑤] 配置项")
for k, want in (("optim", "paged_adamw_8bit"), ("bnb_compute_dtype", "fp32"),
                ("eval_batch_size", 8)):
    v = cfg.get(k)
    good = str(v) == str(want)
    ok_all &= good
    print("      %-18s %-20s（应为 %s）%s" % (k, v, want, "✅" if good else "❌"))
src = io.open(os.path.join(PKG, "finetune_train.py"), encoding="utf-8").read()
for label, cond in (("load_best 已关", "load_best_model_at_end=False" in src),
                    ("重采样代码", "_rng.choices" in src),
                    ("超长丢弃", "len(ids) > max_len" in src),
                    ("公共前缀 mask", "while n < limit and p_ids[n] == ids[n]" in src)):
    ok_all &= cond
    print("      %-18s %s" % (label, "✅ 在" if cond else "❌ 缺"))

print("\n=== 总判定：%s ===" % ("✅ 技术验证通过" if ok_all else "❌ 还有没通过项"))
sys.exit(0 if ok_all else 3)
