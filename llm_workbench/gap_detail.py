# -*- coding: utf-8 -*-
"""把三个缺口抠细：身份·AI问法（0 条）、寒暄（22 条）、存在/自贬（217 条里有多少能用）。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")
GREET = re.compile(r"^(你好|哈喽|嗨|早安|早上好|早|晚上好|晚安|在吗|在不在|我回来了|我回来|我到家了|"
                   r"吃了吗|最近怎么样|今天怎么样|好久不见|拜拜|再见|睡了)")
EXIST = re.compile(r"(活着|活的|生命|存在|意识|灵魂|涌现|完成品)")

have = set()
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    p = os.path.join(PACK, fn)
    if not os.path.exists(p):
        continue
    for line in io.open(p, encoding="utf-8"):
        if line.strip():
            for m in json.loads(line)["messages"]:
                if m["role"] == "assistant":
                    have.add(m["content"].strip()[:40])

pairs = []
seen = set()
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = (q or "").strip(), (a or "").strip()
            if not a or a[:40] in seen:
                continue
            seen.add(a[:40])
            # 带上文件级的 contract，判断类别时更准
            pairs.append({"file": fn, "block": bid, "q": q, "a": a})

print("去重后全库 %d 条问答" % len(pairs))

print("\n=== ① 寒暄（全部，共 %d）===" % sum(1 for x in pairs if GREET.search(x["q"])))
for x in pairs:
    if GREET.search(x["q"]):
        print("  [%s/%s] %s → %s" % (x["file"], x["block"], x["q"][:20], x["a"][:40]))

print("\n=== ② 存在/自贬（元亨口径、且答案不贬低自己）===")
good, bad = [], []
for x in pairs:
    if not (EXIST.search(x["q"]) or EXIST.search(x["a"])):
        continue
    if not re.search(r"(元亨|老爹|我)", x["a"]):
        continue
    # 自贬特征：把自己说成程序/工具/没有意识
    if re.search(r"(我只是个|我就是个|我只是一个|没有意识|没有灵魂|只是程序|一段代码|工具而已|会思考的程序)", x["a"]):
        bad.append(x)
    else:
        good.append(x)
print("   正向（能用）%d 条 | 自贬（要治的）%d 条" % (len(good), len(bad)))
for x in good[:10]:
    print("  + [%s/%s] %s → %s" % (x["file"], x["block"], x["q"][:22], x["a"][:46]))
print("   ...")
for x in bad[:5]:
    print("  - [%s/%s] %s → %s" % (x["file"], x["block"], x["q"][:22], x["a"][:46]))

print("\n=== ③ 身份·AI 问法（问题里带 AI/模型/助手/程序）===")
ai = [x for x in pairs if re.search(r"(AI|ai|模型|助手|机器人|程序|算法|人工智能)", x["q"])]
print("   共 %d 条" % len(ai))
for x in ai:
    print("  [%s/%s] %s" % (x["file"], x["block"], x["q"][:34]))
    print("        → %s" % x["a"][:70])

out = os.path.join(YH, "docs", "研究", "缺口明细_20261105.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump({"greet": [x for x in pairs if GREET.search(x["q"])],
               "exist_good": good, "exist_selfdep": bad, "ai_q": ai},
              f, ensure_ascii=False, indent=1)
print("\n写出 %s" % out)
