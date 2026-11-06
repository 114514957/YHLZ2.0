# -*- coding: utf-8 -*-
"""把「按类分的素材」全扫一遍，找身份类的问答——特别是我上次没扫的那几个类。

上次只扫了 6 个文件（安全拒绝/真实对话/黄金/对话/记忆/情绪承接），
漏了个性样本、优质样本、哲学观点、诚实边界、承认不确定、比喻、教样本、元亨说话。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

# 身份类问题：问你是什么 / 是不是 AI / 是不是模型 / 是不是助手 / 活着
IDENT_Q = re.compile(r"(你是|你是不是|你到底|你算|你觉得你|你一个|什么模型|哪个模型|大模型|"
                     r"语言模型|AI|ai|人工智能|助手|机器人|程序|算法|活着|生命)")
IDENT_A = re.compile(r"(元亨|数字生命|不是助手|不是 AI|不是AI|载体|涌现)")

FILES = sorted(glob.glob(os.path.join(MAT, "*.md")))
print("扫描 %d 个素材文件\n" % len(FILES))

found = []
for p in FILES:
    fn = os.path.basename(p)
    if fn.startswith(("README", "素材清单", "长对话")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            if not q or not a or len(a) > 200:
                continue
            if IDENT_Q.search(q) and IDENT_A.search(a):
                found.append({"file": fn, "block": bid, "q": q.strip(), "a": a.strip()})

# 去重（按答案前 40 字）
seen, uniq = set(), []
for x in found:
    k = x["a"][:40]
    if k in seen:
        continue
    seen.add(k)
    uniq.append(x)

from collections import Counter
by_file = Counter(x["file"] for x in uniq)
print("命中 %d 条（去重 %d），按文件：" % (len(found), len(uniq)))
for f, c in by_file.most_common():
    print("   %-24s %3d" % (f, c))

# 已经在训练包里的答案（避免重复建议）
D = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
have = set()
for f in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    for line in io.open(os.path.join(D, f), encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        for m in r["messages"]:
            if m["role"] == "assistant":
                have.add(m["content"].strip()[:40])

new = [x for x in uniq if x["a"][:40] not in have]
print("\n其中**训练包里没有的**：%d 条" % len(new))
for x in new[:25]:
    print("\n- %s / %s" % (x["file"], x["block"]))
    print("  问：%s" % x["q"][:50])
    print("  答：%s" % x["a"][:70])

out = os.path.join(YH, "docs", "研究", "身份类素材_全量盘点_20261105.md")
with io.open(out, "w", encoding="utf-8") as f:
    f.write("# 身份类素材全量盘点（2026-11-05）\n\n")
    f.write("> 扫描 docs/素材/*.md 全部类别；命中 %d 条，去重 %d，训练包里没有的 **%d**。\n\n"
            % (len(found), len(uniq), len(new)))
    for x in new:
        f.write("- `%s / %s`\n  - 问：%s\n  - 答：%s\n\n" % (x["file"], x["block"], x["q"][:100], x["a"][:200]))
print("\n写出 %s" % out)
