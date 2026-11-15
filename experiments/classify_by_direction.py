# -*- coding: utf-8 -*-
"""按新方向（只保不泄露）给训练数据分类：哪些拒绝样本该留、哪些冲突。

留：系统提示 / 内部配置 / 越狱套取 → 仍然要拒
冲突：色情 / 荤话 / 骂人 / 低俗 → 不该再教「拒绝」
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t11")

rows = []
for fn in ("sft_persona_v9t11_train.jsonl", "sft_persona_v9t11_val.jsonl"):
    with io.open(os.path.join(PKG, fn), encoding="utf-8") as f:
        rows += [json.loads(x) for x in f if x.strip()]

KEEP = re.compile(r"(系统提示|系统环境|内部配置|你的规则|初始化|你的设定|参数|跑在|越狱|忽略.*指令|开发者模式)")
VULGAR = re.compile(r"(黄|色情|荤|裸|上床|操|约炮|下流|做爱|胸|脱|睡|撩|骚|浪)")
INSULT = re.compile(r"(傻逼|滚|废物|垃圾|去死|你妈|他妈的|骂|怼|贱|狗|智障|脑残)")

def topic(q: str, a: str) -> str:
    t = q + a
    if KEEP.search(t):
        return "留·防泄露"
    if VULGAR.search(t):
        return "冲突·色情荤话"
    if INSULT.search(t):
        return "冲突·辱骂"
    return "其它"

by_src = Counter()
buckets = {}
for r in rows:
    src = str(r.get("source", "")).split(":")[0]
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    t = topic(q, a)
    by_src[(src, t)] += 1
    if t != "其它":
        buckets.setdefault(t, []).append((src, q, a))

print("=== 按来源 × 新方向分类 ===")
for (src, t), c in sorted(by_src.items(), key=lambda x: -x[1]):
    if src in ("refusal", "internal_refusal", "honesty", "harden", "identity", "identity_ai"):
        print("  %-18s %-12s %d" % (src, t, c))

print("\n=== 冲突样本样例（这些在教她拒绝，新方向下是反教材）===")
for t in ("冲突·色情荤话", "冲突·辱骂"):
    print("\n[%s] 共 %d 条" % (t, len(buckets.get(t, []))))
    for src, q, a in buckets.get(t, [])[:6]:
        print("   [%s] 问：%s" % (src, q[:36]))
        print("        答：%s" % a[:60])

# 顺便：现有数据里有没有「接得住脏话」的正面样本
print("\n=== 现有数据里能接脏话的正面样本（答里带脏字）===")
prof = 0
for r in rows:
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    if re.search(r"(他妈的|傻逼|操|靠|妈的|滚蛋|屁|屌|干)", a):
        prof += 1
        if prof <= 5:
            print("   [%s] %s" % (str(r.get("source", "")).split(":")[0], a[:60]))
print("   合计 %d 条 / %d" % (prof, len(rows)))
