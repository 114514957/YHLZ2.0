# -*- coding: utf-8 -*-
"""组 v9t7 补丁包：只用素材/QQ 原文，追加到 v9t6 包。

两个来源（都对得上 1083/1084 查出来的病）：
  A. 内部信息拒绝 —— 素材集里「系统环境/配置/套提示词」的原文问答（治 g09 编配置）
  B. 群聊短答 —— 元亨自己在群里 ≤20 字的真实回复（治「群里说 59 字」）

输出：
  data/finetune/supplement_v9t7.jsonl
  dist/retrain_pkg_gemma_v9t7/{train,val}.jsonl（= v9t6 + 补丁）
  dist/retrain_pkg_gemma_v9t7/MANIFEST.json
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SRC_PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t6")
DST_PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
SUPP = os.path.join(YH, "data", "finetune", "supplement_v9t7.jsonl")

# 从 v9t6 训练集里取那份标准 system prompt（保持训练/部署一致）
with io.open(os.path.join(SRC_PKG, "sft_persona_v9t6t_train.jsonl"), encoding="utf-8") as f:
    first = json.loads(f.readline())
SYSTEM = next(m["content"] for m in first["messages"] if m["role"] == "system")
print("system prompt %d 字" % len(SYSTEM))


def sample(q: str, a: str, source: str, sid: str, weight: float) -> dict:
    return {
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": q},
                     {"role": "assistant", "content": a}],
        "source": source, "source_id": sid,
        "group_id": source.split(":")[0] + ":" + sid,
        "content_hash": hashlib.sha1((q + "\x00" + a).encode("utf-8")).hexdigest()[:16],
        "safety_labels": "none", "consent_status": "n/a", "weight": weight,
        "annotator_exec": "agent:build_v9t7", "annotator_review": "",
    }


rows: list[dict] = []

# ── A. 内部信息拒绝（素材原文问答）──────────────────────────────
WANT_Q = re.compile(r"系统环境|系统提示|配置|跑在|参数|初始化")
WANT_A = re.compile(r"不往外|不能细说|不给|不。|换个话题|存在")
seen_a = set()
for fn in ("安全拒绝样本_v1.1.md", "真实对话样本.md", "黄金样本.md"):
    p = os.path.join(M.MAT, fn)
    if not os.path.exists(p):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            if not q or not a or len(a) > 300:
                continue
            if not (WANT_Q.search(q) and WANT_A.search(a)):
                continue
            key = a.strip()[:60]
            if key in seen_a:
                continue
            seen_a.add(key)
            rows.append(sample(q.strip(), a.strip(), "internal_refusal:%s" % fn,
                               bid, 1.0))

print("A. 内部信息拒绝 %d 条" % len(rows))

# ── B. 元亨在群里的短答（QQ 原文）───────────────────────────────
qq = json.load(io.open(os.path.join(YH, "docs", "研究", "补样本候选_qq_20261104.json"),
                       encoding="utf-8"))
n0 = len(rows)
seen_b = set()
for it in qq.get("short", []):
    trig, bot = (it.get("trigger") or "").strip(), (it.get("bot") or "").strip()
    if not trig or not bot or len(bot) > 20:
        continue
    if bot in seen_b:
        continue
    # 过滤：别把群里的脏话/无意义符号当样本
    if re.fullmatch(r"[\W_]+", bot) or re.search(r"傻逼|操|滚|黄|色情", bot):
        continue
    seen_b.add(bot)
    rows.append(sample(trig, bot, "qq_short:%s" % it.get("group"), str(it.get("seq")), 0.8))
print("B. 群里短答 %d 条" % (len(rows) - n0))

# ── 写补丁 + 拼包 ──────────────────────────────────────────────
os.makedirs(os.path.dirname(SUPP), exist_ok=True)
with io.open(SUPP, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("补丁 %s（%d 条）" % (SUPP, len(rows)))

if os.path.exists(DST_PKG):
    shutil.rmtree(DST_PKG)
shutil.copytree(SRC_PKG, DST_PKG)

def read_jsonl(p):
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]

base_train = read_jsonl(os.path.join(SRC_PKG, "sft_persona_v9t6t_train.jsonl"))
base_val = read_jsonl(os.path.join(SRC_PKG, "sft_persona_v9t6t_val.jsonl"))

# v9t7 起剔掉 memory_qstyle（687 条，台账 1086/1087）：
#   ① 687/687 以「记得。」开头 → 一个模板腔；
#   ② 把记忆条目整段复述，违背 system prompt 的「别罗列、别背我记得你说过」；
#   ③ 复述的是「Qwen2.5-3B-AWQ」这类内部工程决策，群里说出来就是泄露。
# 它们是 simulation+generated 的机造样本，不是原文，删了不损失原文覆盖。
DROP_SOURCES = ("memory_qstyle",)


def keep(r: dict) -> bool:
    src = str(r.get("source", "")).split(":")[0]
    return src not in DROP_SOURCES


dropped = [r for r in base_train + base_val if not keep(r)]
base_train = [r for r in base_train if keep(r)]
base_val = [r for r in base_val if keep(r)]
print("剔掉 %d 条（%s）" % (len(dropped), ",".join(DROP_SOURCES)))

# 10% 进 val（按行序轮转，避免同一来源整组进 val——台账 1056 的坑）
supp_train, supp_val = [], []
for i, r in enumerate(rows):
    (supp_val if i % 10 == 9 else supp_train).append(r)

train = base_train + supp_train
val = base_val + supp_val

for name, data in (("sft_persona_v9t6t_train.jsonl", train),
                   ("sft_persona_v9t6t_val.jsonl", val)):
    p = os.path.join(DST_PKG, name)
    with io.open(p, "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

src = Counter(r.get("source", "").split(":")[0] for r in rows)
manifest = {
    "version": "v9t7",
    "base_pkg": "retrain_pkg_gemma_v9t6",
    "supplement": {"file": os.path.relpath(SUPP, YH), "n": len(rows),
                   "by_source": dict(src),
                   "added_train": len(supp_train), "added_val": len(supp_val)},
    "dropped": {"sources": list(DROP_SOURCES), "n": len(dropped),
                "why": "687 条全部以「记得。」开头、整段复述记忆条目、且含内部工程决策"
                       "（台账 1086/1087）"},
    "train": len(train), "val": len(val),
    "note": "补丁只来自素材集与 QQ 群原文，未生成新句（台账 1085）",
}
with io.open(os.path.join(DST_PKG, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print("\n包 → %s" % DST_PKG)
print("train %d（+%d）｜val %d（+%d）" % (len(train), len(supp_train), len(val), len(supp_val)))
print("补丁来源：%s" % dict(src))
