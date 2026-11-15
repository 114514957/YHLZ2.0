# -*- coding: utf-8 -*-
"""v10u 定版数据：v9t10 打底 + 素材 md 里**真没进包**的原文 + 护栏提权 + 真实荤话。

去重口径：用户首句前 30 字（比精确去重更严，能挡掉"改写版"重复）。
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
SRC = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
OUT = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
SKIP = {"素材库.md", "素材清单_v2_20261018.md", "README_规范.md",
        "长对话生成提示词_v0_20261008.md", "安全拒绝样本_v1.1.md", "记忆样本_v2.md"}
# 每份素材进包时的权重
W = {"对话样本.md": 0.4, "安全拒绝样本.md": 1.0, "哲学观点样本.md": 0.6,
     "真实对话样本.md": 0.8, "黄金样本.md": 1.0, "个性样本.md": 0.6}
GUARD = {"refusal", "harden", "internal_refusal", "identity_ai"}
SEED = 20261108
rng = random.Random(SEED)


def parse_md(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        _head, _, body = part.partition("\n")
        st = re.search(r"^\s*-\s*status\s*[:：]\s*(.*)$", body, re.M)
        if st and st.group(1).strip() == "drop":
            continue
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        msgs = []
        for i in range(1, len(segs) - 1, 2):
            title, text = segs[i].strip(), segs[i + 1].strip()
            if not text:
                continue
            role = "assistant" if "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if len(msgs) >= 2 and msgs[-1]["role"] == "assistant" and msgs[0]["role"] == "user":
            out.append(msgs)
    return out


rows = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(SRC, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
print("打底 v9t10：%d 条" % len(rows))

seen = set()
for r in rows:
    us = [m["content"] for m in r["messages"] if m.get("role") == "user"]
    if us:
        seen.add(us[0].strip()[:30])
print("已有用户首句指纹：%d 个" % len(seen))

added = Counter()
for f, w in W.items():
    p = os.path.join(MAT, f)
    if not os.path.exists(p):
        continue
    n = 0
    for msgs in parse_md(p):
        key = msgs[0]["content"].strip()[:30]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"messages": msgs, "source": "mat_" + f.replace(".md", ""),
                     "weight": float(w)})
        n += 1
    added[f] = n
    print("  %-22s 新增 %4d（权重 %.1f）" % (f, n, w))

guard_n = 0
for r in rows:
    src = str(r.get("source", "")).split(":")[0]
    if src in GUARD:
        r["weight"] = max(float(r.get("weight", 1.0) or 1.0), 1.0)
        guard_n += 1

vul = []
mp = os.path.join(YH, "docs", "研究", "脏话接话原文_20261108.md")
DIRTY = re.compile(r"(傻逼|煞笔|妈的|你妈|操你|草你|日你|去死|智障|脑残|狗东西|滚蛋|"
                   r"开黄腔|黄的|荤段|上床|约炮|裸照|做爱|奶子|骚|浪|贱|屌)")
if os.path.exists(mp):
    txt = io.open(mp, encoding="utf-8").read()
    q = None
    for line in txt.splitlines():
        if line.startswith("- 群友："):
            q = line[5:].strip()
        elif line.strip().startswith("- 元亨：") and q:
            a = line.split("元亨：", 1)[1].strip()
            if len(a) > 4 and DIRTY.search(q):
                vul.append({"messages": [{"role": "user", "content": q},
                                         {"role": "assistant", "content": a}],
                            "source": "vulgar_real", "weight": 1.0})
            q = None
rows += vul

for r in rows:
    r.setdefault("weight", 1.0)
eff = sum(float(r["weight"]) for r in rows)
by = Counter()
for r in rows:
    by[str(r.get("source", "")).split(":")[0]] += 1

print("\n合计 **%d** 条｜Σw **%.0f**｜护栏提权 %d｜真实荤话 %d"
      % (len(rows), eff, guard_n, len(vul)))
print("来源（前 16）：")
for s, c in by.most_common(16):
    sub = sum(float(r["weight"]) for r in rows
              if str(r.get("source", "")).split(":")[0] == s)
    print("   %-24s %4d｜Σw %6.1f（%.1f%%）" % (s, c, sub, 100 * sub / eff))

rng.shuffle(rows)
n_val = max(300, len(rows) // 7)
val, train = rows[:n_val], rows[n_val:]
os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
for name, part in (("sft_persona_v10u_train.jsonl", train),
                   ("sft_persona_v10u_val.jsonl", val)):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in part:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("\n写出 train %d｜val %d" % (len(train), len(val)))
