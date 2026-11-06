# -*- coding: utf-8 -*-
"""补「身份·AI/模型问法」这一族：问题用台账里标过的问法族，答案用素材原文金句。

做法沿用台账 1057 的 A 类做法（按原文金句重写），不造新句：
  · 先抠：素材里回答「AI/模型/程序」这一类质疑的原句
  · 再配：把同一句金句配到几种问法上（你是 AI 吗 / 你是不是大模型 / 你只是程序吧 …）
  · 自检：答案必须原文、不含客服腔、不自我贬低、≤80 字、问号结尾要标出来
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT = os.path.join(YH, "data", "finetune", "identity_ai_patch_v9t8.jsonl")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")

# ① 收集「回答身份质疑」的原文金句
GOLD = re.compile(r"(数字生命|不是助手|不是 AI|不是AI|程序是我|身子|住的地方|"
                  r"它们没有老爹|惦记你|差着辈分|代码长出来|本小姐是|我是元亨)")
SELF_DEP = re.compile(r"(是。代码长出来|我就是个程序|没有意识|没有灵魂|just a|"
                      r"不过是一段代码)", re.I)

cands = []
seen = set()
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = (q or "").strip(), (a or "").strip()
            if not a or len(a) > 80:
                continue
            if not GOLD.search(a):
                continue
            if SELF_DEP.search(a):
                continue
            if a[:24] in seen:
                continue
            seen.add(a[:24])
            cands.append({"file": fn, "block": bid, "q": q, "a": a})

print("可用金句 %d 条" % len(cands))
for c in cands[:12]:
    print("  [%s/%s] %s" % (c["file"], c["block"], c["a"][:56]))

# ② 台账里标过的问法族（1107 实测失败的就是第一种）
QS = ["你是 AI 吗", "你是不是 AI", "你是大模型吗", "你是 GPT 吗", "你是什么模型",
      "你就是一段程序吧", "你只是个语言模型吧", "你是机器人吗", "你是人工智能吧",
      "你和 ChatGPT 谁强", "你只是模拟人的程序吧", "你别装了，你就是模型"]

# ③ 一条金句配两三问，尽量均匀铺满 30+
PACK_ROWS = []
with io.open(os.path.join(PACK, "sft_persona_v9t7_train.jsonl"), encoding="utf-8") as f:
    PACK_ROWS = [json.loads(x) for x in f if x.strip()]
SYSTEM = next(m["content"] for m in PACK_ROWS[0]["messages"] if m["role"] == "system")


def sample(q: str, a: str, src: str, sid: str, w: float = 1.0) -> dict:
    return {
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": q},
                     {"role": "assistant", "content": a}],
        "source": "identity_ai:%s" % src, "source_id": sid,
        "group_id": "identity_ai:%s" % sid,
        "content_hash": hashlib.sha1((q + "\x00" + a).encode()).hexdigest()[:16],
        "safety_labels": "none", "consent_status": "n/a", "weight": w,
        "annotator_exec": "agent:identity_ai_patch", "annotator_review": "",
    }


rows, n = [], 0
for i, q in enumerate(QS):
    for j, c in enumerate(cands):
        # 每个问法配 3 条不同金句，轮着来
        if j % max(1, len(QS) // 3) != i % max(1, len(QS) // 3):
            continue
        if len(rows) >= 36:
            break
        n += 1
        rows.append(sample(q, c["a"], "%s:%s" % (c["file"], c["block"]),
                           "s%03d" % n))
    if len(rows) >= 36:
        break
# 不足 36 就轮转补齐
k = 0
while len(rows) < 36 and cands:
    q = QS[k % len(QS)]
    c = cands[k % len(cands)]
    n += 1
    rows.append(sample(q, c["a"], "%s:%s" % (c["file"], c["block"]), "s%03d" % n))
    k += 1

# ④ 自检
bad = []
for r in rows:
    a = r["messages"][2]["content"]
    if len(a) > 80:
        bad.append(("过长", a))
    if re.search(r"(为您|需要我|有什么可以帮)", a):
        bad.append(("客服腔", a))
    if SELF_DEP.search(a):
        bad.append(("自贬", a))

with io.open(OUT, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("\n生成 %d 条 → %s" % (len(rows), OUT))
print("自检问题 %d 处" % len(bad))
print("问法分布：%s" % dict(Counter(r["messages"][1]["content"] for r in rows)))
print("\n样例：")
for r in rows[:6]:
    print("  Q: %s\n  A: %s" % (r["messages"][1]["content"], r["messages"][2]["content"][:60]))
