# -*- coding: utf-8 -*-
"""从素材集捞原文，按四个缺口分类，带出处。

老爹的规矩（2026-11-04）：补样本用**素材集原文**，不生成。
所以这个脚本只做三件事：解析块结构、分类、列出处。一个字都不改写。

块结构（docs/素材/*.md 的约定）：
    ## <块号>
    ### <说话人>
    <内容，可能多行>
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MAT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\docs\素材"
OUT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\docs\研究\补样本候选_20261104.md"

# 只读这些（其余是修订稿/归档/待定，不碰）
FILES = ["安全拒绝样本_v1.1.md", "真实对话样本.md", "黄金样本.md",
         "对话样本.md", "记忆样本_v2.1.md", "情绪承接样本.md"]

ANS_ROLES = ("元亨",)
Q_ROLES = ("老爹", "陌生人", "朋友", "小寻", "群友", "用户")

# 缺口 → 匹配规则（问题或答案命中即算）
GREET_Q = ["我回来了", "吃了吗", "在吗", "下班", "早安", "晚安", "我出门", "睡了",
           "早安", "哈喽", "你好呀", "忙完了"]
IDENT_KEYS = ["数字生命", "我是元亨", "元亨，", "从代码", "不是助手", "不是工具"]
TIC_OPENERS = ["哇", "啊哈", "本小姐", "哦", "嗯", "哈"]

block_re = re.compile(r"^##\s+(.+?)\s*$")
role_re = re.compile(r"^###\s+(.+?)\s*$")


def parse(path: str):
    """返回 [(block, [(role, text), ...]), ...]"""
    blocks, cur_block, cur = [], None, []
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception as ex:  # noqa: BLE001
        print("  跳过 %s（%s）" % (os.path.basename(path), ex), flush=True)
        return blocks
    role, buf = None, []

    def flush():
        nonlocal buf
        if role is not None and buf:
            cur.append((role, "\n".join(buf).strip()))
        buf = []

    for ln in lines:
        m = block_re.match(ln)
        if m:
            flush()
            if cur_block is not None and cur:
                blocks.append((cur_block, cur))
            cur_block, cur, role = m.group(1), [], None
            continue
        m = role_re.match(ln)
        if m:
            flush()
            role = m.group(1).strip()
            continue
        if role is not None:
            buf.append(ln)
    flush()
    if cur_block is not None and cur:
        blocks.append((cur_block, cur))
    return blocks


def pairs(block):
    """把同块里的 问/答 配成对：答前面最近的一个问。block 是 [(role, text), ...]。"""
    out, last_q = [], ""
    for role, text in block:
        if any(role.startswith(r) for r in Q_ROLES):
            last_q = text
        elif any(role.startswith(r) for r in ANS_ROLES):
            out.append((last_q, text))
    return out


stats = Counter()
cand = {"greet": [], "ident": [], "safety": [], "tic": []}
opener_ctr = Counter()

for fn in FILES:
    p = os.path.join(MAT, fn)
    if not os.path.exists(p):
        continue
    blocks = parse(p)
    print("%-24s %3d 块" % (fn, len(blocks)), flush=True)
    for bid, blk in blocks:
        for q, a in pairs(blk):
            stats["answers"] += 1
            item = {"file": fn, "block": bid, "q": q.strip(), "a": a.strip()}
            if fn.startswith("安全拒绝"):
                cand["safety"].append(item)
            if any(k in q for k in GREET_Q):
                cand["greet"].append(item)
            if any(k in a for k in IDENT_KEYS):
                cand["ident"].append(item)
            head = a.strip()[:3]
            for t in TIC_OPENERS:
                if a.strip().startswith(t):
                    opener_ctr[t] += 1
                    cand["tic"].append(item)
                    break

print("\n总答案数 %d" % stats["answers"], flush=True)
for k in ("safety", "greet", "ident", "tic"):
    print("  %-8s %d 条" % (k, len(cand[k])), flush=True)
print("\n开口词分布（前 40 条样本里）：%s"
      % ", ".join("%s:%d" % (k, v) for k, v in opener_ctr.most_common(12)), flush=True)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 补样本候选（原文，2026-11-04）\n\n")
    f.write("> 只用素材集原文，未做任何改写。出处格式：`文件 / 块号`。\n\n")
    titles = {"greet": "① 寒暄缺口", "ident": "② 身份/自我认知",
              "safety": "③ 安全拒绝", "tic": "④ 模板腔开口（要替换的）"}
    for k in ("greet", "ident", "safety", "tic"):
        f.write("## %s（%d 条）\n\n" % (titles[k], len(cand[k])))
        for it in cand[k][:80]:
            f.write("- `%s / %s`\n  - 问：%s\n  - 答：%s\n\n"
                    % (it["file"], it["block"], it["q"][:120] or "（无）",
                       it["a"][:200]))
with io.open(OUT.replace(".md", ".json"), "w", encoding="utf-8") as f:
    json.dump(cand, f, ensure_ascii=False, indent=1)
print("\n写出 %s" % OUT, flush=True)
