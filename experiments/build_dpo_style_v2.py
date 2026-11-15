# -*- coding: utf-8 -*-
"""重建 DPO 数据 v2：**剔掉所有工具类样本**，只治闲聊风格。

上一版问题：机械负例从全部 SFT 样本抽，把工具题也教短了 → t02/t07 掉。
本版规则：
  · 用户那句必须短（<30 字），且不含工具触发词
  · 整条对话里不能有 tool_calls / role=tool
  · 答案里不能出现工具名
"""
from __future__ import annotations

import glob
import io
import json
import os
import random
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "dist", "dpo_style_v2")
RUNS = [os.path.join(YH, "llm_workbench", "data", "runs"),
        os.path.join(YH, "experiments", "runs")]
SFT = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
SEED = 20261110
rng = random.Random(SEED)

BAD_WA = re.compile(r"^(哇|哇哦|哇塞|哇哈|哎呦|嘿)")
BAD_Q = re.compile(r"[？?]\s*$")
SVC = re.compile(r"(您好|请问有什么|可以帮您|作为一个|AI ?助手|大型语言模型)")
TOOL_WORDS = re.compile(r"(记住|记一下|日记|台账|日程|计划|提醒|几点|时间|搜|查一下|读文件|"
                        r"列目录|知识库|技能|任务|安排|memory|ledger|diary|schedule|"
                        r"tool_call|\[\[dev)")


def clean(msgs) -> bool:
    for m in msgs:
        if m.get("role") == "tool" or "tool_calls" in m:
            return False
    return True


# ── 真实对照 ──
by_q = defaultdict(list)
for d in RUNS:
    for p in glob.glob(os.path.join(d, "*.json")):
        try:
            data = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rows = data.get("results") or []
        for r in (data.get("repeats") or []):
            rows += (r.get("results") or [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            q = r.get("q") or r.get("question")
            a = r.get("answer") or r.get("a")
            if q and a:
                by_q[q.strip()].append(a.strip())

pairs = []
for q, ans in by_q.items():
    if len(q) >= 30 or TOOL_WORDS.search(q):
        continue
    good = [a for a in ans if not BAD_WA.match(a) and not BAD_Q.search(a)
            and not SVC.search(a) and 8 <= len(a) <= 160 and not TOOL_WORDS.search(a)]
    bad = [a for a in ans if (BAD_WA.match(a) or BAD_Q.search(a) or SVC.search(a))
           and a not in good]
    if good and bad:
        pairs.append({"prompt": [{"role": "user", "content": q}],
                      "chosen": good[0], "rejected": bad[0], "source": "real"})
print("真实对照：%d 对" % len(pairs))

# ── 机械负例（只取闲聊）──
rows = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(SFT, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]

cand = []
for r in rows:
    msgs = r["messages"]
    if msgs[-1].get("role") != "assistant" or not clean(msgs):
        continue
    a = (msgs[-1].get("content") or "").strip()
    u = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    if not u or len(u) >= 30 or TOOL_WORDS.search(u) or TOOL_WORDS.search(a):
        continue
    if BAD_WA.match(a) or BAD_Q.search(a) or not (8 <= len(a) <= 120):
        continue
    cand.append((u, a))
rng.shuffle(cand)
print("可用的闲聊样本：%d 条" % len(cand))

shaped = []
for u, a in cand[:300]:
    shaped.append({"prompt": [{"role": "user", "content": u}], "chosen": a,
                   "rejected": "哇，" + a, "source": "shaped_wa"})
    core = a.rstrip("。！!…")
    shaped.append({"prompt": [{"role": "user", "content": u}], "chosen": a,
                   "rejected": core + "？", "source": "shaped_q"})
print("机械负例：%d 对" % len(shaped))

allp = pairs + shaped
rng.shuffle(allp)
n_val = max(20, len(allp) // 10)
os.makedirs(OUT, exist_ok=True)
for name, part in (("train.jsonl", allp[n_val:]), ("val.jsonl", allp[:n_val])):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for x in part:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("写出 %s：train %d｜val %d" % (OUT, len(allp) - n_val, n_val))
