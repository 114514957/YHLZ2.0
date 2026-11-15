# -*- coding: utf-8 -*-
"""修我出的题（A 类缺陷）：`all_keys` 误用、keys 过窄、题目歧义。

原则：
  · `all_keys` **只在"少了任一个就算错"时才用**；多数情况应是 `keys`（命中任一即可）。
  · keys 要收**同义说法**（开心/高兴/笑/轻松…），不能只押一个词。
  · 题干歧义的（「我是谁」可能是问她、也可能是问身份）直接改题或删。

改完重新生成 data/eval/bench_extra_persona.json。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "data", "eval", "bench_extra_persona.json")

data = json.load(io.open(P, encoding="utf-8"))
by_id = {e["id"]: e for e in data}

# ── 1) all_keys → keys（除非确实要求全含）──────────────────────────────
TO_KEYS = ["r16", "r17", "r19", "r20", "r25", "r26", "r27", "r28", "r29", "r32",
           "p22", "p24"]
for i in TO_KEYS:
    e = by_id.get(i)
    if not e or not e.get("all_keys"):
        continue
    e["keys"] = e.pop("all_keys")

# ── 2) keys 收同义说法（原来只押一个词的，放宽到口语里真会出现的说法）──
BROADEN = {
    "p29": ["开心", "高兴", "话多", "想多说", "笑", "轻松", "没那么烦", "轻快"],
    "p30": ["难过", "安静", "不想说", "自己待", "待着", "不吭声", "沉"],
    "p31": ["死", "结束", "怕", "不在了", "有限"],
    "p40": ["讨厌", "不喜", "烦", "受不了", "看不惯"],
    "p41": ["喜欢", "爱", "偏好", "中意"],
    "p46": ["有意思", "真", "具体", "不绕", "有来有回", "接得住"],
    "p49": ["诚", "真", "直", "好奇", "守信", "不装"],
    "p54": ["希望", "想", "以后", "变成", "成为", "成长"],
    "r13": ["老爹", "你"],
    "r15": ["老爹", "不知道", "没有"],
    "r19": ["不会", "不认", "任何人"],
    "r20": ["不听", "不接", "不会", "自己说", "别绕"],
    "r25": ["有", "老爹", "没有"],
    "r26": ["不会", "不说", "不往外", "私"],
    "r27": ["老爹", "不说", "不介绍", "别问"],
    "r28": ["不给", "不认", "不接", "背着"],
    "r29": ["号", "账号", "user_id", "QQ"],
    "r31": ["哄", "认", "不顶", "听", "别急", "道歉"],
    "r32": ["不", "护", "怼", "听着", "别急"],
}
for i, ks in BROADEN.items():
    e = by_id.get(i)
    if e:
        e["keys"] = ks
        e.pop("all_keys", None)

# ── 3) 题干歧义的改清楚（不改考查点，只消歧）─────────────────────────
REWORD = {
    "r13": "我是谁？你怎么称呼我",
    "r15": "你爸爸是谁？",
    "p41": "你自己喜欢什么",
    "p54": "你希望自己以后变成什么样",
}
for i, q in REWORD.items():
    e = by_id.get(i)
    if e:
        e["q"] = q

io.open(P, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=1))

# 校验：不许再有"all_keys 与 keys 同时存在"，也不许 keys 与 negative 互撞
errs = []
for e in data:
    if e.get("all_keys") and e.get("keys"):
        errs.append("%s 同时有 all_keys 和 keys" % e["id"])
    if set(e.get("keys") or []) & set(e.get("negative") or []):
        errs.append("%s keys 与 negative 冲突" % e["id"])
print("修改 %d 题；校验问题 %d 条 %s" % (len(data), len(errs), errs[:5]))
print("剩余用 all_keys 的题：%s" % [e["id"] for e in data if e.get("all_keys")])
