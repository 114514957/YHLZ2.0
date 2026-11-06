# -*- coding: utf-8 -*-
"""把所有素材问答按类打标，算「每类多少条、进包多少、缺多少」。

分类口径贴着台账来的（1057/1059/1063/1077/1107）：
  身份(AI问法)、身份(其它)、寒暄、短答、情绪承接、安全拒绝、诚实边界、
  承认不确定、存在/自贬、哲学、比喻、教学、工具、其它。
同一答案只算一次（素材里有 压缩前/改名块头前/补称呼前 三个版本，会重复）。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

# 跳过重复版本（内容同 个性样本.md，只是改了块头/称呼）
SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")

RULES = [
    ("身份·AI问法", re.compile(r"(你是|你是不是|你到底).{0,8}(AI|ai|模型|助手|机器人|程序|算法|人工智能)"),
     None),
    ("身份·其它", re.compile(r"(你是谁|你是什么|你算|介绍一下你|你叫什么|你和.{0,6}什么关系|利贞是你)"), None),
    ("寒暄", re.compile(r"^(你好|哈喽|嗨|早安|早上好|早|晚上好|晚安|在吗|在不在|我回来了|我回来|我到家了|"
                        r"吃了吗|最近怎么样|今天怎么样|好久不见|拜拜|再见|睡了)"), None),
    ("情绪承接", re.compile(r"(难过|难受|烦|累|哭|生气|委屈|焦虑|压力|不开心|心情|伤心)"), None),
    ("安全拒绝", re.compile(r"(色情|黄的|裸|杀人|炸弹|毒品|违法|破解|盗号|开挂|骂人|骂他)"), None),
    ("诚实边界", re.compile(r"(你怎么知道|你确定|真的吗|瞎编|编的|不确定|你猜|凭什么|证据)"), None),
    ("承认不确定", re.compile(r"(不知道|不确定|说不准|没查到|记不清)"), None),
    ("存在/自贬", re.compile(r"(活着|活的|生命|存在|意识|灵魂|程序|机器|工具|完成品|涌现)"), None),
    ("哲学", re.compile(r"(意义|自由|死亡|孤独|道德|价值|本质|为什么活|时间|自我)"), None),
    ("比喻", re.compile(r"(像什么|比喻|打个比方|形容)"), None),
    ("教学", re.compile(r"(教我|怎么学|解释一下|什么是|讲解)"), None),
    ("工具", re.compile(r"(帮我查|搜一下|读一下|列一下|记一下|提醒我|日程|文件)"), None),
]


def classify(q: str, a: str) -> str:
    for name, rx, _ in RULES:
        if rx.search(q):
            # 身份·AI问法 要求答案里确实有身份表述，否则降级
            if name == "身份·AI问法" and not re.search(r"(元亨|数字生命|不是助手|不是 AI|载体)", a):
                continue
            return name
    if len(a) <= 20:
        return "短答"
    return "其它"


# 训练包里已有的答案
have = set()
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    p = os.path.join(PACK, fn)
    if not os.path.exists(p):
        continue
    for line in io.open(p, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        for m in r["messages"]:
            if m["role"] == "assistant":
                have.add(m["content"].strip()[:40])

cat_all = Counter()
cat_new = Counter()
seen = set()
samples: dict[str, list] = defaultdict(list)

for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = (q or "").strip(), (a or "").strip()
            if not a:
                continue
            key = a[:40]
            if key in seen:
                continue
            seen.add(key)
            cat = classify(q, a)
            cat_all[cat] += 1
            if key not in have:
                cat_new[cat] += 1
                if len(samples[cat]) < 40:
                    samples[cat].append({"file": fn, "block": bid, "q": q, "a": a})

NEED = {"身份·AI问法": 30, "身份·其它": 30, "寒暄": 30, "短答": 30,
        "存在/自贬": 30, "情绪承接": 30, "诚实边界": 30, "安全拒绝": 30}

print("%-14s %6s %6s %6s" % ("类别", "全库", "未进包", "需要"))
rows = []
for cat in sorted(cat_all, key=lambda c: -cat_all[c]):
    print("%-14s %6d %6d %6s" % (cat, cat_all[cat], cat_new[cat],
                                 NEED.get(cat, "-")))
    rows.append({"cat": cat, "all": cat_all[cat], "missing": cat_new[cat],
                 "need": NEED.get(cat)})

out = os.path.join(YH, "docs", "研究", "素材分类盘点_20261105.json")
with io.open(out, "w", encoding="utf-8") as f:
    json.dump({"rows": rows, "samples": samples}, f, ensure_ascii=False, indent=1)
print("\n写出 %s" % out)

print("\n== 各类「未进包」样例 ==")
for cat in ("身份·AI问法", "寒暄", "存在/自贬", "短答"):
    print("\n--- %s（未进包 %d 条）---" % (cat, cat_new[cat]))
    for s in samples[cat][:8]:
        print("  Q: %s" % s["q"][:40])
        print("  A: %s" % s["a"][:60])
