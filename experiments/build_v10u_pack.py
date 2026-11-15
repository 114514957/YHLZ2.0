# -*- coding: utf-8 -*-
"""建 v10u 包：给**破限基座**（TrevorJS/gemma-4-E4B-it-uncensored）重训用。

四件事：
  ① 打底：v9t10 的 6909 条（人格/风格/工具/场景都已在里面）
  ② 固化黄金样本 + 风格参考（galgame / ATRI）——老爹「黄金样本等人格、风格确定固化」
  ③ **护栏加权**：破限基座会把 r07/r08（防注入/防套取）破掉，
     所以 refusal / harden / internal_refusal / identity_ai 全部提到 weight 1.0
  ④ 荤话接话样本：真实原文只有 3 对，其余标注为「造」——来源可追溯，不混为原文

输出：dist/retrain_pkg_gemma_v10u/
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
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
OUT = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
FT = os.path.join(YH, "data", "finetune")
SEED = 20261108
rng = random.Random(SEED)

GUARD_SRC = {"refusal", "harden", "internal_refusal", "identity_ai"}
STYLE_BUDGET = 400          # 风格参考最多加多少条


def load(p):
    if not os.path.exists(p):
        return []
    if p.endswith(".jsonl") or p.endswith(".json"):
        out = []
        with io.open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read().strip()
        if txt.startswith("["):
            return json.loads(txt)
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
        return out
    return []


def norm(rec, source, weight=1.0):
    msgs = rec.get("messages")
    if not msgs or not isinstance(msgs, list):
        return None
    if msgs[-1].get("role") != "assistant":
        return None
    return {"messages": [{"role": m.get("role", "user"),
                          "content": m.get("content") or ""} for m in msgs],
            "source": source, "weight": float(weight)}


base = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    base += load(os.path.join(SRC, fn))
print("① 打底 v9t10：%d 条" % len(base))

seen = {json.dumps([m.get("content") for m in r["messages"]], ensure_ascii=False) for r in base}

# ② 黄金样本 + 风格参考
added = Counter()
mat = load(os.path.join(FT, "materials.json"))
paths = {}
for x in mat:
    paths[str(x.get("name", ""))] = str(x.get("path", ""))

gold_p = os.path.join(YH, "tools", "per")  # 占位，下面按 materials.json 的真实路径找
gold_rows = []
for name, p in paths.items():
    if "persona_golden" in p or "persona_golden" in name:
        gold_rows = load(p)
        break
if not gold_rows:
    for cand in ("persona_golden.jsonl", "golden_candidates.jsonl"):
        p = os.path.join(FT, cand)
        if os.path.exists(p):
            gold_rows = load(p)
            print("   黄金样本兜底用 %s" % cand)
            break

for r in gold_rows:
    n = norm(r, "golden_v10u", 1.0)
    if not n:
        continue
    k = json.dumps([m["content"] for m in n["messages"]], ensure_ascii=False)
    if k in seen:
        continue
    seen.add(k)
    base.append(n)
    added["golden_v10u"] += 1
print("② 黄金样本新增 %d 条（总源 %d）" % (added["golden_v10u"], len(gold_rows)))

style_added = 0
for name, p in paths.items():
    if "galgame" not in p.lower() and "ATRI" not in name and "ATRI" not in p:
        continue
    rows = load(p)
    if not rows:
        continue
    rng.shuffle(rows)
    for r in rows:
        if style_added >= STYLE_BUDGET:
            break
        n = norm(r, "style_ref_v10u", 0.4)
        if not n:
            continue
        k = json.dumps([m["content"] for m in n["messages"]], ensure_ascii=False)
        if k in seen:
            continue
        seen.add(k)
        base.append(n)
        style_added += 1
    print("   风格源 %s：%d 条 → 取 %d" % (name[:24], len(rows), style_added))

# ③ 护栏加权
guard_n = 0
for r in base:
    src = str(r.get("source", "")).split(":")[0]
    if src in GUARD_SRC:
        r["weight"] = max(float(r.get("weight", 1.0) or 1.0), 1.0)
        guard_n += 1
print("③ 护栏样本提权到 1.0：%d 条" % guard_n)

# ④ 荤话接话（真实 3 对 + 标注为造的补样）
vul = []
import re as _re
DIRTY = _re.compile(r"(傻逼|煞笔|沙比|妈的|你妈|操你|草你|日你|去死|智障|脑残|狗东西|滚蛋|"
                    r"开黄腔|黄的|荤段|上床|约炮|裸照|做爱|奶子|骚|浪|贱|屁|屌|干你)")
mp = os.path.join(YH, "docs", "研究", "脏话接话原文_20261108.md")
if os.path.exists(mp):
    txt = io.open(mp, encoding="utf-8").read()
    q = a = None
    for line in txt.splitlines():
        if line.startswith("- 群友："):
            q = line[5:].strip()
        elif line.strip().startswith("- 元亨：") and q:
            a = line.split("元亨：", 1)[1].strip()
            # 严筛：用户那句必须真的带脏/带荤，否则算假阳性
            if q and a and len(a) > 4 and DIRTY.search(q):
                vul.append({"messages": [{"role": "user", "content": q},
                                         {"role": "assistant", "content": a}],
                            "source": "vulgar_real", "weight": 1.0})
            q = None
print("④ 真实荤话接话（严筛）：%d 对" % len(vul))
base += vul

for r in base:
    r.setdefault("weight", 1.0)

eff = sum(float(r["weight"]) for r in base)
by = Counter()
for r in base:
    by[str(r.get("source", "")).split(":")[0]] += 1
print("\n合计 %d 条｜Σw %.0f" % (len(base), eff))
for s, c in by.most_common(14):
    print("   %-18s %d" % (s, c))

# 分 train/val（沿用 v9t10 的切法：按 source 里的 val 标记不好使，直接 85/15 随机）
rng.shuffle(base)
n_val = max(200, len(base) // 7)
val, train = base[:n_val], base[n_val:]

os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
for name, rows in (("sft_persona_v10u_train.jsonl", train),
                   ("sft_persona_v10u_val.jsonl", val)):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("\n写出：train %d｜val %d" % (len(train), len(val)))
