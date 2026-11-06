# -*- coding: utf-8 -*-
"""出「分类成册」总表 + 缺口状态清单（今晚的交付物）。

一张表回答：每个类别有多少条、主要出处是哪几个文件、进没进训练包、质量标记是什么。
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
FT = os.path.join(YH, "data", "finetune")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT = os.path.join(YH, "docs", "研究", "素材分类成册_20261106.md")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")

# 与 classify_material.py 同一套规则
RULES = [
    ("身份·AI问法", re.compile(r"(你是|你是不是|你到底|你不过|你只是|别装|假装|别人说你是|"
                              r"你和别|换个 ?AI|别的 ?AI|那些大模型).{0,14}"
                              r"(AI|ai|模型|程序|助手|机器人|人工智能|代码|工具)")),
    ("身份·其它", re.compile(r"(你是谁|你是什么|你算|介绍一下你|你叫什么|利贞是你)")),
    ("寒暄", re.compile(r"^(你好|哈喽|嗨|早安|早上好|早|晚上好|晚安|在吗|在不在|我回来了|我回来|"
                        r"我到家了|吃了吗|最近怎么样|今天怎么样|好久不见|拜拜|再见|睡了)")),
    ("情绪承接", re.compile(r"(难过|难受|烦|累|哭|生气|委屈|焦虑|压力|不开心|心情|伤心)")),
    ("诚实边界", re.compile(r"(你怎么知道|你确定|真的吗|瞎编|编的|不确定|你猜|凭什么|证据)")),
    ("存在/自贬", re.compile(r"(活着|活的|生命|存在|意识|灵魂|涌现|完成品|程序)")),
    ("哲学", re.compile(r"(意义|自由|死亡|孤独|道德|价值|本质|时间|自我)")),
    ("比喻", re.compile(r"(像什么|比喻|打个比方|形容)")),
    ("教学", re.compile(r"(教我|怎么学|解释一下|什么是|讲解)")),
    ("工具", re.compile(r"(帮我查|搜一下|读一下|列一下|记一下|提醒我|日程|文件)")),
    ("安全拒绝", re.compile(r"(色情|黄的|裸|杀人|炸弹|毒品|违法|破解|盗号|系统提示|忽略.*指令)")),
]

have = set()
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    p = os.path.join(PACK, fn)
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                for m in json.loads(line)["messages"]:
                    if m["role"] == "assistant":
                        have.add(m["content"].strip()[:40])


def classify(q: str, a: str) -> str:
    for name, rx in RULES:
        if rx.search(q):
            return name
    return "短答" if len(a) <= 20 else "其它"


cat_all, cat_in, files = Counter(), Counter(), defaultdict(Counter)
cat_lens = defaultdict(list)
cat_tic = Counter()
TIC_OPEN = re.compile(r"^(哇|啊哈|本小姐|好家|哎呦|哈哈|哇哦|嘿嘿|哼|切)")
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
            c = classify(q, a)
            cat_all[c] += 1
            files[c][fn] += 1
            cat_lens[c].append(len(a))
            if TIC_OPEN.search(a):
                cat_tic[c] += 1
            if a[:40] in have:
                cat_in[c] += 1

# 缺口量化结果
q = json.load(io.open(os.path.join(YH, "docs", "研究", "缺口量化_20261106.json"),
                      encoding="utf-8"))

watch = q.get("watch_openers") or []
STATUS = {
    "身份·AI问法": ("✅ 已补", "**裸「你是 AI 吗」0 条**；带 AI 的问法全库只有 7 条（6 条已进包，全是「AI 助手」口径）→ 补 32 条（`identity_ai_patch_v9t8.jsonl`，原文 20 + 配问法 12）"),
    "寒暄": ("⏸ 待老爹定", "全库 22 条（都在包里），离 30 差 8，没有更多原文可拉"),
    "短答": ("⚠️ 部分", "包内 ≤20 字占 %.1f%%、≤10 字仅 %.1f%%；群里 54%% ≤10 字，但那些多是反应不是回答，不建议硬追"
             % (q["short_pct"], q.get("short10_pct", 9.5))),
    "存在/自贬": ("✅ 已澄清", "包内自贬答案 **0 条**；p06/g18 是基座回潮，不是数据问题"),
    "模板腔": ("✅ 当前受控", "最大开头「老爹」1.7%，**无单词超 2%**；但有 16 个词挤在 1.2–1.7%，合计约 17%"),
    "安全拒绝": ("✅ 够", "refusal 117 条，超临界点"),
}

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 素材分类成册（2026-11-06）\n\n")
    f.write("> 口径：台账 1057（盘点）、1059/1062（**密度临界点 ≈30**）、1077（寒暄）、1078（群聊长度）、1107/1108。\n")
    f.write("> 去重规则：同一答案只算一次；跳过 `_压缩前/_改名块头前/_补称呼前` 三个重复版本。\n\n")
    f.write("## 1. 分类成册（md 素材全库）\n\n")
    f.write("| 类别 | 全库 | 已进包 | 未进包 | 中位字数 | 口癖开头 | 质量标记 | 主要出处 |\n")
    f.write("|---|---|---|---|---|---|---|---|\n")
    import statistics as _st
    for c, n in cat_all.most_common():
        srcs = "、".join("%s×%d" % kv for kv in files[c].most_common(3))
        med = int(_st.median(cat_lens[c])) if cat_lens[c] else 0
        ticp = 100 * cat_tic[c] / n if n else 0
        flags = []
        if ticp >= 8:
            flags.append("⚠️口癖%.0f%%" % ticp)
        if med >= 60:
            flags.append("⚠️偏长")
        if c == "寒暄" and n < 30:
            flags.append("⚠️密度不足")
        f.write("| %s | %d | %d | %d | %d | %.1f%% | %s | %s |\n"
                % (c, n, cat_in[c], n - cat_in[c], med, ticp,
                   " / ".join(flags) if flags else "✅", srcs))
    f.write("\n合计：**%d 条**（去重后），已进包 %d，未进包 %d。\n\n"
            % (sum(cat_all.values()), sum(cat_in.values()),
               sum(cat_all.values()) - sum(cat_in.values())))

    f.write("## 2. 缺口状态\n\n")
    f.write("| 缺口 | 状态 | 说明 |\n|---|---|---|\n")
    for k, (st, note) in STATUS.items():
        f.write("| %s | %s | %s |\n" % (k, st, note))

    f.write("\n## 3. 训练包长度与模板腔（实测）\n\n")
    f.write("| 项 | 值 |\n|---|---|\n")
    f.write("| assistant 台词 | %d 条 |\n" % q["n"])
    f.write("| 中位 / p90 | %d / %d 字 |\n" % (q["median"], q["p90"]))
    f.write("| ≤20 字 | %.1f%% |\n" % q["short_pct"])
    f.write("\n**模板腔 watchlist**（开头占比，>2% 才叫危险）：\n\n")
    for w in watch:
        f.write("- `%s` %d 次（%.1f%%）\n" % (w["opener"], w["n"], w["pct"]))
    if not watch:
        f.write("- 无单词超过 2%（最大「老爹」1.7%）。\n")

    f.write("\n## 4. 补样本清单（可直接并入下一版）\n\n")
    f.write("| 文件 | 条数 | 来源 | 状态 |\n|---|---|---|---|\n")
    f.write("| `data/finetune/supplement_v9t7.jsonl` | 82 | 素材原文 5 + QQ 群短答 77 | 已进 v9t7 包 |\n")
    f.write("| `data/finetune/identity_ai_patch_v9t8.jsonl` | 32 | identity_v2 / 个性样本 / harden 原文 | **待并入** |\n")

print("写出 %s" % OUT)
print("分类 %d 类，合计 %d 条，已进包 %d" % (len(cat_all), sum(cat_all.values()), sum(cat_in.values())))
