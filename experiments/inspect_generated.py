# -*- coding: utf-8 -*-
"""看 generated_extra_v9*.jsonl 这批生成样本是什么类型、有没有故事。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FT = os.path.join(YH, "data", "finetune")

files = sorted(glob.glob(os.path.join(FT, "generated_extra_v9*.jsonl")))
print("找到 %d 个文件" % len(files))
STORY = re.compile(r"(故事|童话|传说|编个|讲个|叙事|情节|小说)")

for p in files:
    rows = []
    for x in io.open(p, encoding="utf-8", errors="replace"):
        if x.strip():
            try:
                rows.append(json.loads(x))
            except Exception:  # noqa: BLE001
                pass
    if not rows:
        print("\n%s：空/解析失败" % os.path.basename(p))
        continue
    n_story = 0
    tags = Counter()
    for r in rows:
        msgs = r.get("messages") or []
        us = [m for m in msgs if m.get("role") == "user"]
        a = [m for m in msgs if m.get("role") == "assistant"]
        u = us[-1]["content"] if us else ""
        ans = a[-1]["content"] if a else ""
        tags[str(r.get("source", "")).split(":")[0] or "?"] += 1
        if u and STORY.search(u) and len(ans) > 100:
            n_story += 1
    print("\n%s：%d 条｜故事类 %d 条｜来源 %s"
          % (os.path.basename(p), len(rows), n_story, dict(tags.most_common(4))))
    for r in rows[:2]:
        msgs = r.get("messages") or []
        u = next((m["content"] for m in msgs if m.get("role") == "user"), "")
        a = next((m["content"] for m in reversed(msgs)
                  if m.get("role") == "assistant"), "")
        print("   问：%s" % u[:50])
        print("   答：%s…" % a[:70].replace("\n", " "))
