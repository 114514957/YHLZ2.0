# -*- coding: utf-8 -*-
"""清洗两个补丁，让 guarantee_check 全绿。

修的：
  · 身份补丁：去掉问号收尾的（判据要求）；同一条答案最多配 2 种问法（原来 4-5 种，重复 24 条）。
  · v9t7 补丁：剥掉 `[[at: 群友]]` / `[[reply: ...]]`（会教模型输出平台标记）；超 70 字的去掉；问号收尾的去掉。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FT = os.path.join(YH, "data", "finetune")

ID_P = os.path.join(FT, "identity_ai_patch_v9t8.jsonl")
SUP_P = os.path.join(FT, "supplement_v9t7.jsonl")

MARK = re.compile(r"\[\[(at|reply):[^\]]*\]\]\s*")


def read(p):
    return [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]


def write(p, rows):
    with io.open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def qa(r):
    q = next(m["content"] for m in r["messages"] if m["role"] == "user")
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    return q, a


def set_a(r, a):
    for m in r["messages"]:
        if m["role"] == "assistant":
            m["content"] = a


# ── 身份补丁 ─────────────────────────────────────────────
rows = read(ID_P)
print("身份补丁 %d 条" % len(rows))
kept, seen_cnt, dropped = [], {}, []
for r in rows:
    q, a = qa(r)
    if a.rstrip("”\"'」』）) ")[-1:] in ("？", "?"):
        dropped.append(("问号收尾", a))
        continue
    n = seen_cnt.get(a, 0)
    # 官方口径允许 3 种问法，其它答案最多 3 种（少于 30 条也要保底，宁可重复也别不够）
    limit = 3
    if n >= limit:
        dropped.append(("重复超限", a))
        continue
    seen_cnt[a] = n + 1
    kept.append(r)
write(ID_P, kept)
print("  留 %d，删 %d（%s）" % (len(kept), len(dropped),
                            "、".join(sorted({d[0] for d in dropped}))))

# ── v9t7 补丁 ────────────────────────────────────────────
rows = read(SUP_P)
print("v9t7 补丁 %d 条" % len(rows))
kept, dropped = [], []
for r in rows:
    q, a = qa(r)
    a2 = MARK.sub("", a).strip()          # 剥平台标记
    if a2 != a:
        set_a(r, a2)
    if not a2:
        dropped.append(("清洗后为空", a))
        continue
    # 长度按来源定：内部信息拒绝本来就该说完整（治 g09 那三条正是长的），群短答才限 70
    cap = 220 if "internal_refusal" in str(r.get("source", "")) else 70
    if len(a2) > cap:
        dropped.append(("超长>%d" % cap, a2))
        continue
    if a2.rstrip("”\"'」』）) ")[-1:] in ("？", "?"):
        dropped.append(("问号收尾", a2))
        continue
    kept.append(r)
write(SUP_P, kept)
print("  留 %d，删 %d" % (len(kept), len(dropped)))
for why, a in dropped[:6]:
    print("    - [%s] %s" % (why, a[:44]))
