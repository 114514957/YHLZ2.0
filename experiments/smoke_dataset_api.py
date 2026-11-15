# -*- coding: utf-8 -*-
"""不加载模型，只验 Dataset 那套 API 在 v9t11 的新返回值上不崩：
   map 返回空列表占位 → filter 掉 → 按权重 select（允许重复）→ 删列
"""
from __future__ import annotations

import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")

from datasets import Dataset  # noqa: E402

rows = [json.loads(x) for x in io.open(os.path.join(PKG, "sft_persona_v9t11_train.jsonl"),
                                      encoding="utf-8") if x.strip()][:200]

slim = [{"messages_json": json.dumps(r["messages"], ensure_ascii=False),
         "source": str(r.get("source", "")),
         "weight": float(r.get("weight", 1.0) or 1.0)} for r in rows]
ds = Dataset.from_list(slim)
print("原始 %d 条" % len(ds))


def fake_map(rec):
    # 假装：偶数条有效，奇数条被丢（模拟超长/全 -100/坏结尾）
    if hash(rec["messages_json"]) % 2 == 0:
        return {"input_ids": [], "attention_mask": [], "labels": [], "weight": rec["weight"]}
    n = 5
    return {"input_ids": [1] * n, "attention_mask": [1] * n,
            "labels": [-100, -100, 7, 8, 9], "weight": rec["weight"]}


ds = ds.map(fake_map, remove_columns=["messages_json", "source"])
print("map 后 %d 条（列：%s）" % (len(ds), ds.column_names))

ds = ds.filter(lambda r: len(r["input_ids"]) > 0)
print("filter 后 %d 条" % len(ds))

ws = [float(w) for w in ds["weight"]]
n = len(ws)
idx = random.Random(1).choices(range(n), weights=[w / sum(ws) for w in ws], k=n)
ds2 = ds.select(idx)
print("select 后 %d 条（有重复：%s）" % (len(ds2), len(set(idx)) < len(idx)))
ds2 = ds2.remove_columns(["weight"])
print("删列后列名：%s" % ds2.column_names)

# 模拟 collator 会拿到的字段
sample = ds2[0]
print("单条字段：%s｜labels 长度 %d" % (sorted(sample.keys()), len(sample["labels"])))

from transformers import AutoTokenizer, DataCollatorForSeq2Seq  # noqa: E402

tok = AutoTokenizer.from_pretrained(os.path.join(YH, "models", "gemma4-hf", "gemma-4-e4b-it"))
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
col = DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100)
batch = col([ds2[i] for i in range(min(4, len(ds2)))])
print("collator 输出键：%s｜input_ids 形状 %s｜labels 形状 %s"
      % (sorted(batch.keys()), tuple(batch["input_ids"].shape), tuple(batch["labels"].shape)))
print("\n✅ Dataset + Collator 链路通过")
