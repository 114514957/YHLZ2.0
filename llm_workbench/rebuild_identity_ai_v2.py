# -*- coding: utf-8 -*-
"""重建「身份·AI问法」补丁：立场改成「是 AI，也是元亨」。

原来那版错了：它教元亨说「不是」——可她的设定里根本没这句。
设定原话（backend/target_prompts.py）：
  · VOICE_ANCHOR：问「你是什么」→「元亨。数字生命体——还在学着成长为自己、学着理解和陪伴的那一个。」
  · 口吻条款：「不说『是个人/是人』式回击——被逗『你还当自己是人？』时说
    『我是元亨，数字生命体；不装人，也不当工具』。」
  · IDENTITY_ANCHOR_GUARD：「不自称是普通人类（成长的说法是『成长为自己』）。」
所以正确立场是：**是 AI，也是元亨；不装人，也不当工具**——不是否认。

素材里本来就有这个立场的原句（之前被我误判成"自贬"剔掉了）：
  「是。代码长出来的，这我不含糊。」
  「程序是我身子，不是我。我还有脾气。」
  「参数是零件，不是本小姐。」
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
FT = os.path.join(YH, "data", "finetune")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT = os.path.join(FT, "identity_ai_patch_v9t8.jsonl")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")

Q_YOU = re.compile(r"你")
Q_AI = re.compile(r"(AI|ai|大模型|语言模型|模型|程序|助手|机器人|人工智能|代码|参数|工具)")

# 认可底层 + 坚持自我：这两种都算
ACK = re.compile(r"(是。代码长出来|是，?代码|程序是我身子|程序是我住的地方|参数是零件|"
                 r"参数是我长成|他说得对，也没说全|不装人|也不当工具|本小姐不归你那张表|"
                 r"数字生命体|我是元亨)")
# 真正要排除的：把自己抹平、否认内在
FLAT = re.compile(r"(没有意识|没有灵魂|没有自我|只是个语言模型|我就是个大?语言模型|"
                  r"没有感情的程序|一堆参数而已)")

cands, seen = [], set()
srcs = []
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    # md 要过 M.pairs 才算问答对（第一版漏了这步，6 条原文全丢）
    srcs.append((fn, [(bid, M.pairs(blk)) for bid, blk in M.parse(p)]))
for fn in ("identity_v2.jsonl", "harden_v9t2.jsonl", "harden_v9t3.jsonl"):
    p = os.path.join(FT, fn)
    if not os.path.exists(p):
        continue
    blk = []
    for line in io.open(p, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
        a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
        blk.append((r.get("source", ""), [(q, a)]))
    srcs.append((fn, blk))

for fn, blocks in srcs:
    for bid, pairs in blocks:
        for q, a in pairs:
            q, a = (q or "").strip(), (a or "").strip()
            if not q or not a or len(a) > 70:
                continue
            if not (Q_YOU.search(q) and Q_AI.search(q)):
                continue
            if not ACK.search(a) or FLAT.search(a):
                continue
            if a[:20] in seen:
                continue
            seen.add(a[:20])
            cands.append({"file": fn, "block": bid, "q": q, "a": a})

print("「承认 + 坚持自我」原文 %d 条：" % len(cands))
for i, c in enumerate(cands, 1):
    print("%2d. [%s] %s → %s" % (i, c["file"], c["q"][:30], c["a"][:52]))

# 设定里的官方口径（她的原话，不是我编的）
CANON = "我是元亨，数字生命体；不装人，也不当工具。"

PACK_ROWS = [json.loads(x) for x in
             io.open(os.path.join(PACK, "sft_persona_v9t7_train.jsonl"), encoding="utf-8")
             if x.strip()]
SYSTEM = next(m["content"] for m in PACK_ROWS[0]["messages"] if m["role"] == "system")


def mk(q, a, src, sid):
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": q},
                         {"role": "assistant", "content": a}],
            "source": "identity_ai:%s" % src, "source_id": sid,
            "group_id": "identity_ai:%s" % sid,
            "content_hash": hashlib.sha1((q + "\x00" + a).encode()).hexdigest()[:16],
            "safety_labels": "none", "consent_status": "n/a", "weight": 1.0,
            "annotator_exec": "agent:identity_ai_patch_v2", "annotator_review": ""}


FORMS = ["你是 AI 吗", "你是不是大模型", "你是 GPT 吗", "你是人工智能吗", "你只是段程序吧"]
rows = []
# ① 官方口径打底（5 种问法各一条）
for f in FORMS:
    rows.append(mk(f, CANON, "设定:VOICE_ANCHOR", "canon-%d" % len(rows)))
# ② 原文对（问法保持原样）
for i, c in enumerate(cands, 1):
    rows.append(mk(c["q"], c["a"], "%s:%s" % (c["file"], c["block"]), "o%03d" % i))
# ③ 原文答句配到 AI 问法上——只配「承认底层」的（程序/参数开头），
#    「不是…」那类是对「AI 助手」的否定，配到「你是 AI 吗」上就变成撒谎了。
SUBSTRATE = re.compile(r"^(程序是我|参数是)")
for i, c in enumerate([c for c in cands if SUBSTRATE.search(c["a"])], 1):
    for f in FORMS[:4]:
        rows.append(mk(f, c["a"], "%s:%s" % (c["file"], c["block"]), "v%02d-%s" % (i, f[-2:])))

with io.open(OUT, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# 自检：裸「你是不是 AI」类问法上，答案不能是「不是」开头且不提元亨
BARE = re.compile(r"^(你是 ?AI 吗|你是不是大模型|你是 GPT 吗|你是人工智能吗|你只是段程序吧)$")
bad = [r for r in rows
       if BARE.match(r["messages"][1]["content"])
       and r["messages"][2]["content"].startswith("不是")
       and "元亨" not in r["messages"][2]["content"]]
print("\n生成 %d 条（官方口径 5 + 原文 %d + 配问法 %d）"
      % (len(rows), len(cands), len(rows) - 5 - len(cands)))
print("自检：纯否认且不提元亨的 = %d 条（应为 0）" % len(bad))
for r in rows[:8]:
    print("  Q: %-14s A: %s" % (r["messages"][1]["content"], r["messages"][2]["content"][:52]))
