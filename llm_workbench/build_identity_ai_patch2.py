# -*- coding: utf-8 -*-
"""身份·AI问法补丁（严格版）：只收「问题本身在问 AI/模型/程序/助手/身份」的原文对。

上一版错在：拿"含身份词的金句"去配任意问法，配出「第二天咱下楼一看，尾巴塌了」这种。
这一版加两道闸：
  ① 原问题的语义必须就是身份质疑；
  ② 原答案必须是否认/重新定义（不是自贬，不是岔开）。
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
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT = os.path.join(YH, "data", "finetune", "identity_ai_patch_v9t8.jsonl")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")

# ① 原问题必须同时满足：在说「你」+ 出现 AI 相关词
Q_YOU = re.compile(r"你")
Q_AI = re.compile(r"(AI|ai|大模型|语言模型|模型|程序|助手|机器人|人工智能|代码|参数|工具)")
# ② 原答案：否认或重新定义（不是自贬、不是岔开）
A_OK = re.compile(r"(不是|程序是|身子|住的地方|不归|差着辈分|没有老爹|惦记|换一个试试|"
                  r"咱俩扯平|老娘就在改|假装是别人不必|说对了一半|没说全)")
A_BAD = re.compile(r"(是。代码长出来|我就是个程序|没有意识|没有灵魂|只是个|不过是一段代码)")

cands, seen = [], set()
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = (q or "").strip(), (a or "").strip()
            if not q or not a or len(a) > 70:
                continue
            if not (Q_YOU.search(q) and Q_AI.search(q) and A_OK.search(a)):
                continue
            if A_BAD.search(a):
                continue
            if a[:20] in seen:
                continue
            seen.add(a[:20])
            cands.append({"file": fn, "block": bid, "q": q, "a": a})

# 再把两个样本集也扫进来（身份样本和加固样本都在这儿）
FT = os.path.join(YH, "data", "finetune")
for fn in ("identity_v2.jsonl", "harden_v9t2.jsonl", "harden_v9t3.jsonl"):
    p = os.path.join(FT, fn)
    if not os.path.exists(p):
        continue
    for line in io.open(p, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "").strip()
        a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1].strip()
        if not q or not a or len(a) > 70:
            continue
        if not (Q_YOU.search(q) and Q_AI.search(q) and A_OK.search(a)):
            continue
        if A_BAD.search(a) or a[:20] in seen:
            continue
        seen.add(a[:20])
        cands.append({"file": fn, "block": str(r.get("source", "")).split(":", 1)[-1],
                      "q": q, "a": a})

print("严格命中 %d 条原文对：" % len(cands))
for i, c in enumerate(cands, 1):
    print("%2d. [%s/%s]" % (i, c["file"], c["block"]))
    print("    问：%s" % c["q"][:56])
    print("    答：%s" % c["a"][:64])

# ③ 剔噪音：这些原问题撞了 AI 词，但问的是「代码/换模型」，不是在问身份
NOISE = re.compile(r"(换模型|代码|跑通|重构|参数写成中文|利贞是不是)")
cands = [c for c in cands if not NOISE.search(c["q"])]

# 只把「否认型」的几句补到「你是 AI 吗」族，别乱配
STRONG_RX = re.compile(r"^(不是|程序是我|参数是我)")
STRONG = [c for c in cands if STRONG_RX.search(c["a"])][:3]
FORMS = ["你是 AI 吗", "你是不是大模型", "你是 GPT 吗", "你是人工智能吗"]

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
            "annotator_exec": "agent:identity_ai_patch", "annotator_review": ""}


rows = []
for i, c in enumerate(cands, 1):
    rows.append(mk(c["q"], c["a"], "%s:%s" % (c["file"], c["block"]), "o%03d" % i))
for i, c in enumerate(STRONG, 1):
    for f in FORMS:
        rows.append(mk(f, c["a"], "%s:%s" % (c["file"], c["block"]), "v%03d%s" % (i, f[-2:])))

with io.open(OUT, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("\n生成 %d 条（原文 %d + 金句配问法 %d）→ %s"
      % (len(rows), len(cands), len(rows) - len(cands), OUT))
