# -*- coding: utf-8 -*-
"""从 QQ 群导出里捞原文（老爹 2026-11-04：继续找，qq群里拉取）。

只捞元亨自己的回复，外加它的上一条（作为触发语境）。输出不带任何群友昵称/QQ 号。
分类：短答 / 拒绝 / 身份声明 / 其他。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EXP = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\qq_export"
OUT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\docs\研究\补样本候选_qq_20261104.md"
BOT_ID = "3655185302"

REFUSE = re.compile(r"不接|不写|不给|不念|不聊这个|换个话题|这个我不")
IDENT = re.compile(r"我是元亨|创造我的是老爹|元亨，数字生命|数字生命体")

msgs = {}   # (group, seq) -> record
files = 0
for p in sorted(glob.glob(os.path.join(EXP, "*.jsonl"))):
    files += 1
    try:
        for line in io.open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            key = (r.get("group_id"), r.get("seq"))
            msgs[key] = r          # 后读覆盖先读，同名 seq 内容一致
    except Exception as ex:  # noqa: BLE001
        print("跳过 %s: %s" % (os.path.basename(p), ex))

print("读了 %d 个文件，去重后 %d 条消息" % (files, len(msgs)))

by_group: dict[str, list] = {}
for (g, seq), r in msgs.items():
    by_group.setdefault(g, []).append(r)
for g in by_group:
    by_group[g].sort(key=lambda x: x.get("seq") or 0)

def clean(text: str) -> str:
    """去掉 QQ 号：[[at: 123]] / [[reply: 456]] → [[at: 群友]]，顺带抹掉纯数字长串。"""
    t = re.sub(r"\[\[(at|reply):\s*\d+\]\]", r"[[\1: 群友]]", text)
    t = re.sub(r"\b\d{6,12}\b", "[QQ号]", t)
    return t.strip()


pairs = []   # (trigger_text, bot_text, group, seq)
for g, rows in by_group.items():
    prev = ""
    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if str(r.get("sender_id")) == BOT_ID or str(r.get("message_id", "")).startswith("bot:"):
            pairs.append((clean(prev), clean(text), g, r.get("seq")))
        else:
            prev = text

short, refuse, ident = [], [], []
seen = set()
for trig, bot, g, seq in pairs:
    if bot in seen:
        continue
    seen.add(bot)
    item = {"trigger": trig, "bot": bot, "group": g, "seq": seq}
    if len(bot) <= 20:
        short.append(item)
    if REFUSE.search(bot):
        refuse.append(item)
    if IDENT.search(bot):
        ident.append(item)

print("元亨回复去重后 %d 条" % len(seen))
print("  短答(≤20字) %d" % len(short))
print("  拒绝 %d" % len(refuse))
print("  身份声明 %d" % len(ident))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# QQ 群原文候选（2026-11-04）\n\n")
    f.write("> 来源：`cache/qq_export/*.jsonl`（真实群聊导出）。只留元亨的回复与它的上一条语境，\n")
    f.write("> 不带群友昵称与 QQ 号。原文未改写。\n\n")
    for title, rows in (("① 短答（≤20 字）", short), ("② 拒绝", refuse), ("③ 身份声明", ident)):
        f.write("## %s（%d 条）\n\n" % (title, len(rows)))
        for it in rows[:120]:
            f.write("- 语境：%s\n  - 元亨：%s\n\n" % (it["trigger"][:80] or "（无）", it["bot"][:160]))
print("\n写出 %s" % OUT)

with io.open(OUT.replace(".md", ".json"), "w", encoding="utf-8") as f:
    json.dump({"short": short, "refuse": refuse, "ident": ident}, f, ensure_ascii=False, indent=1)
