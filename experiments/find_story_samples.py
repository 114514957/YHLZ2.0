# -*- coding: utf-8 -*-
"""找「讲故事」类样本：用户要故事，答是长篇叙事（长句天然达标）。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
FT = os.path.join(YH, "data", "finetune")
MAT = os.path.join(YH, "docs", "素材")

ASK_STORY = re.compile(r"(讲个故事|讲一个故事|故事|编个|瞎编|讲一段|说个故事|写个故事|"
                       r"讲点|来点故事|聊斋|童话|传说)")
LONG = 35


def long_ratio(a):
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    if not sents:
        return 0.0, 0
    return sum(1 for s in sents if len(s) >= LONG) / len(sents), len(sents)


def scan_messages(msgs, tag, out):
    us = [m for m in msgs if m.get("role") == "user"]
    as_ = [m for m in msgs if m.get("role") == "assistant"]
    if not us or not as_:
        return
    u, a = us[-1].get("content") or "", as_[-1].get("content") or ""
    if not ASK_STORY.search(u) or len(a) < 80:
        return
    ratio, n = long_ratio(a)
    if n >= 3 and ratio >= 0.4:
        out.append({"u": u[:60], "a": a, "ratio": ratio, "n": n, "tag": tag})


hits = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        for x in io.open(p, encoding="utf-8"):
            if x.strip():
                scan_messages(json.loads(x)["messages"], os.path.basename(p), hits)

for p in glob.glob(os.path.join(FT, "generated_extra_v9*.jsonl")) + \
         glob.glob(os.path.join(FT, "sft_persona_v9t*_train.jsonl")):
    if os.path.exists(p):
        try:
            for x in io.open(p, encoding="utf-8", errors="replace"):
                if x.strip():
                    scan_messages(json.loads(x)["messages"], os.path.basename(p), hits)
        except Exception:  # noqa: BLE001
            pass

if os.path.isdir(MAT):
    for f in sorted(os.listdir(MAT)):
        if not f.endswith(".md"):
            continue
        md = io.open(os.path.join(MAT, f), encoding="utf-8", errors="replace").read()
        for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
            _h, _, body = part.partition("\n")
            segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
            u = a = ""
            for i in range(1, len(segs) - 1, 2):
                t, txt = segs[i].strip(), segs[i + 1].strip()
                if "老爹" in t or "用户" in t:
                    u = txt
                elif "元亨" in t:
                    a = txt
            if u and a:
                scan_messages([{"role": "user", "content": u},
                               {"role": "assistant", "content": a}], f, hits)

seen = set()
uniq = []
for h in hits:
    k = h["a"][:60]
    if k in seen:
        continue
    seen.add(k)
    uniq.append(h)

print("讲故事候选：%d 条（去重 %d）" % (len(hits), len(uniq)))
for h in sorted(uniq, key=lambda x: -x["ratio"])[:6]:
    print("\n  问：%s" % h["u"])
    print("  长句率 %.0f%%（%d 句）｜来源 %s" % (100 * h["ratio"], h["n"], h["tag"]))
    print("  答：%s…" % h["a"][:110].replace("\n", " "))
