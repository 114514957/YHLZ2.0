# -*- coding: utf-8 -*-
"""从 QQ 群导出里捞**群友**的原文（老爹 2026-11-04：要的是群友的，不是元亨的）。

为什么：元亨的台词都是人写的（素材集），但它的病是"不像真人说话"——
长句、客服腔、反问收尾。真人怎么在群里说话，只能从群友的消息里看。

输出：群友消息的分层样本 + 与元亨的句长对照。不带昵称/QQ 号。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EXP = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\qq_export"
OUT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\docs\研究\群友语料候选_20261104.md"
BOT_ID = "3655185302"

QQ_RE = re.compile(r"\b\d{6,12}\b")
AT_RE = re.compile(r"\[\[(at|reply):\s*\d+\]\]")


def clean(t: str) -> str:
    t = AT_RE.sub(r"[[\1: 群友]]", t or "")
    t = QQ_RE.sub("[QQ号]", t)
    return t.strip()


msgs = {}
for p in sorted(glob.glob(os.path.join(EXP, "*.jsonl"))):
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        msgs[(r.get("group_id"), r.get("seq"))] = r

human, bot = [], []
for r in msgs.values():
    t = clean(r.get("text") or "")
    if not t:
        continue
    is_bot = (str(r.get("sender_id")) == BOT_ID
              or str(r.get("message_id", "")).startswith("bot:"))
    (bot if is_bot else human).append(t)


def stats(rows, label):
    lens = [len(t) for t in rows]
    med = statistics.median(lens)
    short = sum(1 for l in lens if l <= 10)
    long_ = sum(1 for l in lens if l > 40)
    print("%-6s %5d 条 | 中位 %3d 字 | ≤10 字 %4.1f%% | >40 字 %4.1f%%"
          % (label, len(rows), med, 100 * short / len(rows), 100 * long_ / len(rows)))
    return med


print("去重后 %d 条" % len(msgs))
mh = stats(human, "群友")
mb = stats(bot, "元亨")

# 群友的高频短句（≤6 字）
short_ctr = Counter(t for t in human if 1 <= len(t) <= 6)
print("\n群友高频短句（≤6 字）Top 25：")
for t, c in short_ctr.most_common(25):
    print("   %-8s ×%d" % (t, c))

# 开场词（取前两个字）
op = Counter(t[:2] for t in human if len(t) >= 2)
print("\n群友开头两字 Top 15：%s"
      % ", ".join("%s×%d" % (k, v) for k, v in op.most_common(15)))

# 分层：寒暄 / 应答 / 吐槽 / 提问 / 其他
GREET = re.compile(r"^(早|在吗|来了|哈喽|你好|晚安|睡|走|下班|吃|我回来|兄弟们|大家好)")
ACK = re.compile(r"^(嗯|行|好|对|是|可以|收到|懂了|确实|哈哈|草|啊|哦|咦|诶)")
ASK = re.compile(r"[?？]$")
MOOD = re.compile(r"(累|烦|难过|开心|笑死|绝了|卧槽|唉|无语|崩)")

buckets = {"greet": [], "ack": [], "ask": [], "mood": [], "other": []}
for t in human:
    if len(t) > 60:
        continue
    if GREET.search(t):
        buckets["greet"].append(t)
    elif ACK.search(t):
        buckets["ack"].append(t)
    elif ASK.search(t):
        buckets["ask"].append(t)
    elif MOOD.search(t):
        buckets["mood"].append(t)
    else:
        buckets["other"].append(t)

print("\n分层：" + " | ".join("%s %d" % (k, len(v)) for k, v in buckets.items()))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 群友语料候选（2026-11-04）\n\n")
    f.write("> 来源 `cache/qq_export/*.jsonl`。**只取群友（非元亨）**的消息，已去昵称/QQ 号，原文未改写。\n")
    f.write("> 用途：元亨的「真人怎么说」参照——它现在的病是长句/客服腔/反问收尾。\n\n")
    f.write("## 句长对照\n\n| | 条数 | 中位字数 |\n|---|---|---|\n")
    f.write("| 群友 | %d | **%d** |\n| 元亨 | %d | **%d** |\n\n" % (len(human), mh, len(bot), mb))
    f.write("## 高频短句（≤6 字）\n\n")
    for t, c in short_ctr.most_common(40):
        f.write("- `%s` ×%d\n" % (t, c))
    titles = {"greet": "① 寒暄", "ack": "② 应答", "ask": "③ 提问", "mood": "④ 情绪/吐槽", "other": "⑤ 其他"}
    for k in ("greet", "ack", "ask", "mood", "other"):
        rows = list(dict.fromkeys(buckets[k]))   # 去重保序
        f.write("\n## %s（去重 %d 条）\n\n" % (titles[k], len(rows)))
        for t in rows[:120]:
            f.write("- %s\n" % t.replace("\n", " "))
print("\n写出 %s" % OUT)

with io.open(OUT.replace(".md", ".json"), "w", encoding="utf-8") as f:
    json.dump({"stats": {"human_n": len(human), "human_median": mh,
                         "bot_n": len(bot), "bot_median": mb},
               "short_top": short_ctr.most_common(200),
               "buckets": buckets}, f, ensure_ascii=False, indent=1)
